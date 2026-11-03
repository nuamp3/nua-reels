# assets branch
Raw Stay With Me footage (4K, 25 fps), split losslessly into parts under 100 MB with `ffmpeg -c copy -f segment -segment_time 45`.
Rejoin a clip: `ffmpeg -f concat -safe 0 -i list.txt -c copy clip.mov` with the parts in order.
