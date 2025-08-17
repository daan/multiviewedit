import argparse
import sys
from pathlib import Path

import av
from tqdm import tqdm

def get_video_info(video_path):
    """Gets video information using PyAV."""
    try:
        with av.open(str(video_path)) as container:
            if not container.streams.video:
                raise ValueError(f"No video stream found in {video_path}")
            video_stream = container.streams.video[0]

            frame_rate = video_stream.average_rate
            if not frame_rate or frame_rate <= 0:
                raise ValueError(f"Could not determine frame rate for {video_path}")

            nb_frames = video_stream.frames
            if nb_frames == 0:  # Fallback for containers that don't store frame count
                if video_stream.duration and video_stream.time_base:
                    duration_sec = video_stream.duration * float(video_stream.time_base)
                    nb_frames = int(duration_sec * float(frame_rate))
                else:
                    # Last resort: decode and count frames
                    nb_frames = sum(1 for _ in container.decode(video=0))

            if nb_frames == 0:
                raise ValueError(f"Could not determine frame count for {video_path}")

            has_audio = bool(container.streams.audio)

            return {
                'frame_rate': float(frame_rate),
                'nb_frames': nb_frames,
                'has_audio': has_audio
            }
    except av.AVError as e:
        raise IOError(f"Error opening or reading video file {video_path}: {e}") from e

def trim_video(in_video_file_path, out_video_file_path, frame_start, frame_end):
    """
    Trims a video to a specific frame range (inclusive). Frame-accurate.
    """
    with av.open(str(in_video_file_path)) as in_container:
        in_video = in_container.streams.video[0]
        in_audio = in_container.streams.audio[0] if in_container.streams.audio else None

        with av.open(str(out_video_file_path), 'w') as out_container:
            out_video = out_container.add_stream('libx264', rate=in_video.average_rate)
            out_video.width = in_video.width
            out_video.height = in_video.height
            out_video.pix_fmt = in_video.pix_fmt if in_video.pix_fmt else 'yuv420p'
            out_video.options = {
                'crf': '18', 'preset': 'medium', 'movflags': '+faststart'
            }

            out_audio = None
            if in_audio:
                out_audio = out_container.add_stream('aac', rate=in_audio.rate, layout=in_audio.layout)
                out_audio.options = {'b:a': '192k'}

            start_pts = {}
            streams_to_process = [s for s in [in_video, in_audio] if s]

            frame_num = -1
            trim_complete = False

            with tqdm(total=frame_start, desc="Finding start frame", unit="frame", disable=frame_start <= 0) as pbar_find, \
                 tqdm(total=frame_end - frame_start + 1, desc="Trimming video", unit="frame") as pbar_trim:

                for packet in in_container.demux(streams_to_process):
                    if packet.dts is None:
                        continue

                    if packet.stream.type == 'video':
                        for frame in packet.decode():
                            frame_num += 1

                            if frame_num < frame_start:
                                pbar_find.update(1)
                                continue
                            
                            if frame_num > frame_end:
                                trim_complete = True
                                break
                            
                            if frame_num >= frame_start:
                                if in_video not in start_pts:
                                    if pbar_find.n < pbar_find.total:
                                        pbar_find.update(pbar_find.total - pbar_find.n)
                                    start_pts[in_video] = frame.pts
                                    if in_audio:
                                        audio_start_time = frame.pts * float(in_video.time_base)
                                        start_pts[in_audio] = int(audio_start_time / float(in_audio.time_base))
                                
                                frame.pts -= start_pts[in_video]
                                for p in out_video.encode(frame):
                                    out_container.mux(p)
                                pbar_trim.update(1)
                    
                    elif packet.stream.type == 'audio' and in_video in start_pts:
                        for frame in packet.decode():
                            if frame.pts >= start_pts.get(in_audio, frame.pts):
                                if in_audio not in start_pts: # Should be set by video
                                    continue
                                frame.pts -= start_pts[in_audio]
                                for p in out_audio.encode(frame):
                                    out_container.mux(p)

                    if trim_complete:
                        break

            for p in out_video.encode(None):
                out_container.mux(p)
            if out_audio:
                for p in out_audio.encode(None):
                    out_container.mux(p)


def trim_to_sequence(in_video_file_path, out_dir_path, frame_start, frame_end, timeline_start_frame):
    """
    Trims a video to a specific frame range and outputs as a high-quality JPG image sequence.
    """
    output_path = Path(out_dir_path)
    output_path.mkdir(parents=True, exist_ok=True)

    with av.open(str(in_video_file_path)) as container:
        output_frame_num = timeline_start_frame
        frame_count = -1

        with tqdm(total=frame_start, desc="Finding start frame", unit="frame", disable=frame_start <= 0) as pbar_find, \
             tqdm(total=frame_end - frame_start + 1, desc="Exporting sequence", unit="frame") as pbar_export:

            for frame in container.decode(video=0):
                frame_count += 1

                if frame_count < frame_start:
                    pbar_find.update(1)
                    continue

                if frame_count > frame_end:
                    break

                if frame_count >= frame_start:
                    if pbar_find.n < pbar_find.total:
                        pbar_find.update(pbar_find.total - pbar_find.n)
                    
                    output_filename = output_path / f"{output_frame_num:06d}.jpg"
                    frame.to_image().save(str(output_filename), quality=95)
                    output_frame_num += 1
                    pbar_export.update(1)


def main():
    parser = argparse.ArgumentParser(description="Trim a video to a specific frame range.")
    parser.add_argument("in_video_file_path", help="Path to input video file")
    parser.add_argument("out_video_file_path", help="Path to output video file")
    parser.add_argument("frame_start", type=int, help="Start frame number (inclusive)")
    parser.add_argument("frame_end", type=int, help="End frame number (inclusive)")
    args = parser.parse_args()

    try:
        print(f"Trimming {args.in_video_file_path} from frame {args.frame_start} to {args.frame_end}...")
        trim_video(args.in_video_file_path, args.out_video_file_path, args.frame_start, args.frame_end)
        print(f"Successfully trimmed video and saved to {args.out_video_file_path}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
