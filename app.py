import asyncio
import os
from io import BytesIO
from mimetypes import guess_type

import aiohttp
import requests
import streamlit as st
from deepgram import Deepgram
from pytube import YouTube

from st_custom_components import st_audiorec

__version__ = "0.1.0"

st.set_page_config(
    page_title="Deepgram API Playground",
    page_icon="▶️",
)

MODELS = {
    "Nova": "nova",
    "Whisper Cloud": "whisper-medium",
    "Enhanced": "enhanced",
    "Base": "base",
}

LANGUAGES = {
    "Automatic Language Detection": None,
    "English": "en",
    "French": "fr",
    "Hindi": "hi",
}


@st.cache_data
def _read_from_url(url: str) -> BytesIO:
    return BytesIO(requests.get(url).content)


@st.cache_data
def _read_from_youtube(url: str) -> str:
    yt = YouTube(url)

    video = yt.streams.filter(only_audio=True).first()

    out_file = video.download()
    base, ext = os.path.splitext(out_file)
    audio_file = f"{base}.mp3"

    if os.path.isfile(audio_file):
        os.remove(audio_file)
    os.rename(out_file, audio_file)

    return audio_file


async def streaming(url: str, options: dict[str, str]) -> None:
    # Create a websocket connection to Deepgram
    try:
        deepgramLive = await deepgram.transcription.live(options)
    except Exception as e:
        st.error(f"Could not open socket: {e}")
        return

    # Listen for the connection to close
    deepgramLive.register_handler(
        deepgramLive.event.CLOSE,
        lambda c: st.warning(f"Connection closed with code {c}"),
    )

    # Listen for any transcripts received from Deepgram and write them to the console
    deepgramLive.register_handler(deepgramLive.event.TRANSCRIPT_RECEIVED, st.write)

    # Listen for the connection to open and send streaming audio from the URL to Deepgram
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as audio:
            while True:
                data = await audio.content.readany()
                deepgramLive.send(data)

                # If no data is being sent from the live stream, then break out of the loop.
                if not data:
                    break

    # Indicate that we've finished sending data by sending the customary zero-byte message to the Deepgram streaming endpoint,
    # and wait until we get back the final summary metadata object
    await deepgramLive.finish()


@st.cache_data
def prerecorded(source, options: dict[str, str]) -> None:
    # Send the audio to Deepgram and get the response
    response = deepgram.transcription.sync_prerecorded(source=source, options=options)
    # Write the response to the console
    if detected_language := response["results"]["channels"][0].get("detected_language", None):
        st.write(
            f"🔠 __Detected language:__ {detected_language} ({list(LANGUAGES.keys())[list(LANGUAGES.values()).index(detected_language)]})"
        )

    # FIXME: Parse multichannel response
    if summarize:
        tab1, tab2, tab3 = st.tabs(["📝Response", "🗒️Transcript", "🤏Summary"])
        try:
            tab3.write(
                response["results"]["channels"][0]["alternatives"][0]["summaries"][0]["summary"]
            )
        except Exception as e:
            st.error(e)
    else:
        tab1, tab2 = st.tabs(["📝Response", "🗒️Transcript"])
    try:
        tab1.write(response)
    except Exception as e:
        st.error(e)
    try:
        if paragraphs or smart_format:
            tab2.write(
                response["results"]["channels"][0]["alternatives"][0]["paragraphs"]["transcript"]
            )
        else:
            tab2.write(response["results"]["channels"][0]["alternatives"][0]["transcript"])
    except Exception as e:
        st.error(e)


st.header("🛝Deepgram API Playground", divider="violet")

lcol, mcol, rcol = st.columns(3)
audio_format = lcol.selectbox(
    "️️️️️🗄️Format",
    options=[
        "Prerecorded",
        "Streaming",
    ],
)

if audio_format == "Streaming":
    del LANGUAGES["Automatic Language Detection"]

language = mcol.selectbox(
    "🔠 Language",
    options=list(LANGUAGES.keys()),
    help="⚠️Some features are [only accessible in certain languages](https://developers.deepgram.com/documentation/features/)",
)

lang_options = {
    "detect_language"
    if language == "Automatic Language Detection"
    else "language": True
    if language == "Automatic Language Detection"
    else LANGUAGES[language]
}

model = rcol.selectbox(
    "🤖 Model",
    options=list(MODELS.keys()),
    help="[Models overview](https://developers.deepgram.com/docs/models-overview)",
)

with st.sidebar:
    with st.expander("🛠️Setup", expanded=True):
        st.info("🚀Sign up for a [Free API key](https://console.deepgram.com/signup)")

        deepgram_api_key = st.text_input(
            "🔐 Deepgram API Key",
            type="password",
            placeholder="Enter your Deepgram API key",
            help="""
            The [Deepgram API key](https://developers.deepgram.com/docs/authenticating) can also be passed through 
            [Streamlit secrets](https://docs.streamlit.io/streamlit-community-cloud/deploy-your-app/secrets-management) or
            the `DEEPGRAM_API_KEY` environment variable""",
        )

        if deepgram_api_key == "":
            if "DEEPGRAM_API_KEY" in st.secrets:
                deepgram_api_key = st.secrets["DEEPGRAM_API_KEY"]
            elif "DEEPGRAM_API_KEY" in os.environ:
                deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")

        deepgram = Deepgram(deepgram_api_key)

    # TODO: Add find&replace, keywords, sample rate
    # TODO: Better handling of disabled features (don't turn on by default)
    # FIXME: Handle case when language is changed after unsupported feature is selected
    with st.expander("🦾 Features", expanded=True):
        if channels := st.checkbox(
            "Channels",
            help="Specify the number of independent audio channels your submitted streaming audio contains",
            value=audio_format == "Streaming",
            disabled=audio_format != "Streaming",
        ):
            num_channels = st.number_input("Number of channels", min_value=1)
        else:
            num_channels = 1

        detect_topics = st.checkbox(
            "Topic Detection",
            help="Indicates whether Deepgram will identify and extract key topics for sections of content",
            value=audio_format == "Prerecorded",
            disabled=audio_format != "Prerecorded",
        )

        diarize = st.checkbox("Diarization", help="Indicates whether to recognize speaker changes")

        detect_entities = st.checkbox(
            "Entity Detection",
            help="Indicates whether Deepgram will identify and extract key entities for sections of content",
            value=audio_format == "Prerecorded",
            disabled=audio_format != "Prerecorded",
        )

        encoding = st.selectbox(
            "Encoding",
            options=["linear16", "flac", "mulaw", "amr-nb", "amr-nb", "opus", "speex"],
            help="Specify the expected encoding of the submitted streaming audio",
            disabled=audio_format != "Streaming",
        )

        endpointing = st.checkbox(
            "Endpointing",
            help="Returns transcripts when pauses in speech are detected",
            value=audio_format == "Streaming",
            disabled=audio_format != "Streaming",
        )

        interim_results = st.checkbox(
            "Interim results",
            help="""Provides preliminary results for streaming audio to solve the need for immediate 
            results combined with high levels of accuracy""",
            value=audio_format == "Streaming",
            disabled=audio_format != "Streaming",
        )

        multichannel = st.checkbox(
            "Multichannel",
            help="Recognizes multiple audio channels and transcribes each channel independently",
        )

        paragraphs = st.checkbox(
            "Paragraphs",
            help="""Indicates whether Deepgram will split audio into paragraphs to improve transcript readability. 
            When paragraphs is set to true, punctuate will also be set to true""",
            value=audio_format == "Prerecorded",
            disabled=audio_format != "Prerecorded",
        )

        profanity_filter = st.checkbox(
            "Profanity filter",
            help="Indicates whether to remove profanity from the transcript",
        )

        punctuate = st.checkbox(
            "Punctuation",
            help="Indicates whether to add punctuation and capitalization to the transcript",
        )

        if redact := st.checkbox(
            "Redaction",
            help="Indicates whether to redact sensitive information, replacing redacted content with asterisks (*)",
        ):
            lcol, rcol = st.columns([1, 14])
            numbers = rcol.checkbox("Numbers", help="Aggressively redacts strings of numerals")
            pci = rcol.checkbox(
                "PCI",
                help="Redacts sensitive credit card information, including credit card number, expiration date, and CVV",
            )
            ssn = rcol.checkbox("SSN", help="Redacts social security numbers")
        else:
            pci = ssn = numbers = None
        redact_options = [
            "pci" if pci else None,
            "ssn" if ssn else None,
            "numbers" if numbers else None,
        ]

        if search := st.checkbox(
            "Search",
            help="""
            Terms or phrases to search for in the submitted audio. 
            Deepgram searches for acoustic patterns in audio rather than text patterns in transcripts 
            because we have noticed that acoustic pattern matching is more performant.
            """,
        ):
            search_terms = st.text_input(
                "Search terms",
                placeholder="TERM_1, TERM_2",
                help="Enter terms as comma-separated values",
            )
        else:
            search_terms = ""

        smart_format = st.checkbox(
            "Smart Format",
            help="""Smart Format improves readability by applying additional formatting. 
            When enabled, the following features will be automatically applied: 
            Punctuation, Numerals, Paragraphs, Dates, Times, and Alphanumerics""",
        )

        summarize = st.checkbox(
            "Summarization",
            help="""Indicates whether Deepgram will provide summaries for sections of content. 
            When Summarization is enabled, Punctuation will also be enabled by default""",
            value=audio_format == "Prerecorded",
            disabled=audio_format != "Prerecorded",
        )

        if utterances := st.checkbox(
            "Utterences",
            help="""Segments speech into meaningful semantic units. 
                By default, when utterances is enabled, it starts a new utterance after 0.8s of silence. 
                You can customize the length of time used to determine where to split utterances with the utt_split parameter""",
            value=audio_format == "Prerecorded",
            disabled=audio_format != "Prerecorded",
        ):
            utt_split = st.number_input(
                "Utterance split",
                min_value=0.0,
                step=0.1,
                value=0.8,
                help="""Length of time in seconds of silence between words that Deepgram will use 
                when determining where to split utterances. Default is 0.8""",
            )
        else:
            utt_split = 0.8

    with st.expander("📚Resources"):
        st.write("📖 [Docs](https://developers.deepgram.com/docs)")
        st.write("📟 [Dev Console](https://console.deepgram.com/)")
        st.write("🤗 [Community Support](https://github.com/orgs/deepgram/discussions/)")

    with open("sidebar.html", "r", encoding="UTF-8") as sidebar_file:
        sidebar_html = sidebar_file.read().replace("{VERSION}", __version__)

    st.components.v1.html(sidebar_html, height=600)


if audio_format == "Streaming":
    url = st.text_input(
        "Streaming audio URL",
        key="url",
        value="http://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
    )

else:
    # TODO: Extract audio from video for all modes
    audio_source = st.radio(
        "Choose audio source",
        options=[
            "🎶 Pick a sample file",
            "️🗣 Record audio️",
            "⬆️ Upload audio file",
            "🌐 Load from URL",
        ],
        horizontal=True,
    )

    if audio_source == "⬆️ Upload audio file":
        st.session_state["audio"] = st.file_uploader(
            label="⬆️ Upload audio file",
            label_visibility="collapsed",
        )
        st.session_state["mimetype"] = (
            st.session_state["audio"].type if st.session_state["audio"] else None
        )

    elif audio_source == "🌐 Load from URL":
        audio_yt = st.radio(
            "Source type",
            options=["Audio URL", "Youtube link"],
            horizontal=True,
            label_visibility="collapsed",
        )
        url = st.text_input(
            "URL",
            key="url",
            value="https://static.deepgram.com/examples/interview_speech-analytics.wav"
            if audio_yt == "Audio URL"
            else "https://www.youtube.com/shorts/3tfFDXGsMV8",
        )

        if url != "":
            try:
                if audio_yt == "Audio URL":
                    st.session_state["audio"] = _read_from_url(url)
                else:
                    st.session_state["audio"] = _read_from_youtube(url)
            except Exception as e:
                st.error(e)

    elif audio_source == "️🗣 Record audio️":
        st.session_state["audio"] = st_audiorec()

    else:
        st.session_state["audio"] = "assets/sample_file.wav"
        st.session_state["mimetype"] = guess_type(st.session_state["audio"])[0]

    if st.session_state["audio"] and audio_source != "️🗣 Record audio️":
        st.audio(st.session_state["audio"])

options = {
    "model": MODELS[model],
    list(lang_options.keys())[0]: list(lang_options.values())[0],
    "channels": num_channels,
    "detect_topics": detect_topics,
    "diarize": diarize,
    "detect_entities": detect_entities,
    "encoding": encoding,
    "endpointing": endpointing,
    "interim_results": interim_results,
    "multichannel": multichannel,
    "paragraphs": paragraphs,
    "profanity_filter": profanity_filter,
    "punctuate": punctuate,
    "redact": [option for option in redact_options if option],
    "smart_format": smart_format,
    "summarize": summarize,
    "search": f"""[{search_terms or ""}]""",
    "utterances": utterances,
    "utt_split": utt_split,
}

options = {k: options[k] for k in options if options[k]}

if audio_format == "Prerecorded":
    # Check whether requested file is local, uploaded or remote, and prepare source
    if audio_source == "🌐 Load from URL":
        # file is remote
        if audio_yt == "Audio URL":
            source = {"url": url}
        else:
            source = {
                "buffer": open(st.session_state["audio"], "rb"),
                "mimetype": "audio/mpeg",
            }
    elif audio_source in (["⬆️ Upload audio file", "️🗣 Record audio️"]):
        # file is uploaded/recorded
        source = {
            "buffer": st.session_state["audio"],
            "mimetype": st.session_state["mimetype"]
            if audio_source == "⬆️ Upload audio file"
            else "audio/wav",
        }
        display_source = {
            "buffer": "AUDIO_FILE",
            "mimetype": st.session_state["mimetype"]
            if audio_source == "⬆️ Upload audio file"
            else "audio/wav",
        }
    else:
        # file is local
        source = {
            "buffer": open(st.session_state["audio"], "rb"),
            "mimetype": st.session_state["mimetype"],
        }

    # Write code
    with st.expander("🧑‍💻 Code", expanded=False):
        st.code(
            f"""response = dg_client.transcription.sync_prerecorded( 
    {source if audio_source not in (["⬆️ Upload audio file", "️🗣 Record audio️"]) else display_source}, 
    {options}
)"""
        )
else:
    # TODO: Show code for Streaming input
    pass

if st.button(
    "🪄 Transcribe",
    use_container_width=True,
    type="primary",
    disabled=not deepgram_api_key,
    help="" if deepgram_api_key else "Enter your Deepgram API key",
):
    if audio_format == "Streaming":
        st.info("Use the 'Stop' button at the top right to stop transcription", icon="⏹️")
        asyncio.run(streaming(url, options))
    else:
        prerecorded(source, options)
