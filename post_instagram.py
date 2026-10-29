#!/usr/bin/env python3
"""Publishes due Instagram TRIAL reels from schedule.json via the official Instagram API
(Instagram API with Instagram Login, graph.instagram.com). Stdlib only.
State is kept in posted.json so nothing is ever posted twice."""
import datetime, json, os, sys, time, urllib.error, urllib.parse, urllib.request

API = os.environ.get('IG_API', 'https://graph.instagram.com/v23.0')
TOKEN = os.environ.get('IG_TOKEN', '').strip()
MEDIA_BASE = os.environ.get('MEDIA_BASE', '').rstrip('/')
MAX_LATE_H = float(os.environ.get('MAX_LATE_HOURS', '6'))
MAX_PER_RUN = int(os.environ.get('MAX_PER_RUN', '2'))
ONLY = os.environ.get('ONLY_ID', '').strip()          # manual run: post one specific id now
CHECK = os.environ.get('CHECK_ONLY', '') == '1'       # manual run: just verify the token


def call(method, path, params):
    params = dict(params, access_token=TOKEN)
    q = urllib.parse.urlencode(params)
    if method == 'GET':
        req = urllib.request.Request(f'{API}{path}?{q}')
    else:
        req = urllib.request.Request(f'{API}{path}', data=q.encode(), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')
        raise RuntimeError(f'{method} {path} -> HTTP {e.code}: {body}') from None


def make_container(uid, item, url):
    params = {'media_type': 'REELS', 'video_url': url, 'caption': item['caption'],
              'trial_params': json.dumps({'graduation_strategy': item.get('graduation', 'MANUAL')})}
    if item.get('thumb_offset_ms') is not None:
        params['thumb_offset'] = str(item['thumb_offset_ms'])
    cid = call('POST', f'/{uid}/media', params)['id']
    for _ in range(72):  # wait up to 12 min for Instagram to process the video
        time.sleep(10)
        s = call('GET', f'/{cid}', {'fields': 'status_code,status'})
        code = s.get('status_code')
        if code == 'FINISHED':
            return cid
        if code in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'container {cid} failed: {s}')
    raise RuntimeError(f'container {cid} still processing after 12 min')


def save(state):
    with open('posted.json', 'w') as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
        f.write('\n')


def main():
    if not TOKEN:
        print('IG_TOKEN secret is not set yet - nothing to do.')
        return 0
    me = call('GET', '/me', {'fields': 'user_id,username'})
    uid = me.get('user_id') or me['id']
    print(f"Authenticated as @{me.get('username')} ({uid})")
    if CHECK:
        return 0
    sched = json.load(open('schedule.json'))
    state = json.load(open('posted.json')) if os.path.exists('posted.json') else {}
    now = datetime.datetime.now(datetime.timezone.utc)
    done = 0
    for item in sorted(sched, key=lambda x: x['due']):
        rid = item['id']
        st = state.get(rid, {})
        if st.get('status') == 'published':
            continue
        due = datetime.datetime.fromisoformat(item['due'])
        if ONLY:
            if rid != ONLY:
                continue
        else:
            if due > now:
                continue
            late_h = (now - due).total_seconds() / 3600
            if late_h > MAX_LATE_H:
                if st.get('status') != 'missed':
                    state[rid] = dict(st, status='missed', due=item['due'], note=f'{late_h:.1f} h late, skipped')
                    save(state)
                continue
            if st.get('attempts', 0) >= 3:
                continue
        if done >= MAX_PER_RUN:
            break
        urls = [u for u in (item.get('url') or f"{MEDIA_BASE}/{item['file']}", item.get('url_fallback')) if u]
        try:
            mid, errs = None, []
            for url in urls:
                print(f'{rid}: creating trial reel container from {url}')
                try:
                    cid = make_container(uid, item, url)
                    mid = call('POST', f'/{uid}/media_publish', {'creation_id': cid})['id']
                    break
                except Exception as e:
                    errs.append(str(e)); print(f'  attempt failed: {e}')
            if mid is None:
                raise RuntimeError(' | '.join(errs))
        except Exception as e:  # nothing was published
            st = state.get(rid, {})
            st.update(status='error', due=item['due'], attempts=st.get('attempts', 0) + 1, last_error=str(e)[:600])
            state[rid] = st
            save(state)
            print(f'ERROR {rid}: {e}')
            continue
        # published: record immediately so a later failure can never cause a duplicate
        state[rid] = {'status': 'published', 'due': item['due'], 'media_id': mid,
                      'published_at': now.isoformat(timespec='seconds')}
        save(state)
        done += 1
        try:
            info = call('GET', f'/{mid}', {'fields': 'permalink,timestamp'})
            state[rid].update(permalink=info.get('permalink'), published_at=info.get('timestamp'))
            save(state)
        except Exception as e:
            print(f'(published {rid} but could not read permalink: {e})')
        print(f"PUBLISHED {rid} {state[rid].get('permalink', mid)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
