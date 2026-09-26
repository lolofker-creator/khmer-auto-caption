# Smey AI Dubbing — Human Voice Upload Patch
# Add this feature without changing the existing Download Video section.

import os, subprocess, tempfile
import streamlit as st

def _human_voice_duration(path):
    # Uses the app's existing ffmpeg() helper.
    return audio_duration(path)

def mix_human_voice_with_original(video_path, human_voice_path, output_path, keep_original_music=True):
    """Mix uploaded human voice into the video.
    Keeps the original audio quietly underneath when requested.
    """
    temp_dir = os.path.dirname(output_path)
    voice_wav = os.path.join(temp_dir, "human_voice.wav")

    cmd = [ffmpeg(), "-y", "-i", human_voice_path,
           "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", voice_wav]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="ignore")[-3000:])

    if keep_original_music:
        cmd = [
            ffmpeg(), "-y",
            "-i", video_path,
            "-i", voice_wav,
            "-filter_complex",
            "[0:a]volume=0.18[bg];[1:a]volume=1.25[voice];"
            "[bg][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mix]",
            "-map", "0:v:0", "-map", "[mix]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path
        ]
    else:
        cmd = [
            ffmpeg(), "-y", "-i", video_path, "-i", voice_wav,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path
        ]

    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("បញ្ចូល Human Voice ទៅវីដេអូមិនបាន:\n" +
                           r.stderr.decode("utf-8", errors="ignore")[-5000:])
    return output_path

# UI block — put directly under the existing AI Dubbing block.
with st.expander("🎙️ Human Voice — សម្លេងមនុស្សពិត", expanded=False):
    st.caption("Upload សម្លេងដែលអ្នកថតដោយមនុស្សផ្ទាល់ ហើយបញ្ចូលទៅក្នុងវីដេអូ។")

    human_video = st.file_uploader(
        "📤 Upload Video",
        type=["mp3", "wav", "m4a", "aac", "ogg", "flac"]
        key="human_voice_video"
    )
    human_voice = st.file_uploader(
        "🎙️ Upload Human Voice",
        type=["mp3", "wav", "m4a", "aac", "ogg"],
        key="human_voice_audio"
    )

    keep_music = st.checkbox(
        "🎵 រក្សា Background Music ដើម",
        value=True,
        key="human_voice_keep_music"
    )

    if st.button("🎬 បញ្ចូល Human Voice", type="primary",
                 key="human_voice_mix_button"):
        if not human_video:
            st.warning("សូម Upload Video ជាមុន")
            st.stop()
        if not human_voice:
            st.warning("សូម Upload សម្លេងមនុស្សជាមុន")
            st.stop()

        temp_dir = tempfile.mkdtemp()
        input_video = os.path.join(temp_dir, "input.mp4")
        input_voice = os.path.join(temp_dir, "human_voice")
        output_video = os.path.join(temp_dir, "Smey_Human_Voice.mp4")

        with open(input_video, "wb") as f:
            f.write(human_video.getbuffer())

        voice_ext = os.path.splitext(human_voice.name)[1] or ".mp3"
        input_voice += voice_ext
        with open(input_voice, "wb") as f:
            f.write(human_voice.getbuffer())

        try:
            with st.spinner("🎙️ កំពុងបញ្ចូលសម្លេងមនុស្ស..."):
                mix_human_voice_with_original(
                    input_video,
                    input_voice,
                    output_video,
                    keep_original_music=keep_music
                )

            st.success("✅ Human Voice រួចរាល់!")
            st.video(output_video)

            with open(output_video, "rb") as f:
                st.download_button(
                    "📥 Download Human Voice MP4",
                    f.read(),
                    file_name="Smey_Human_Voice.mp4",
                    mime="video/mp4",
                    key="download_human_voice"
                )
        except Exception as e:
            st.error(f"❌ មិនអាចបញ្ចូល Human Voice បាន: {e}")
