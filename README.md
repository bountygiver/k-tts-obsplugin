# k-tts-obsplugin
OBS plugin to extend donation alerts from kofi using various edge-tts features

# Installation

1. Download and extract from [the latest release](https://github.com/bountygiver/k-tts-obsplugin/releases/latest)

2. Add a **Media Source** and a **Browser source** to your OBS with the following settings. Add these sources to the scene you want the TTS to speak and the alerts to appear.
    - Media Source: ![Added media source settings](readme-imgs\media-source-settings.png)
    - Browser Source: Enable `Local file` checkbox and choose the `overlay.html` from the extracted files as the `Local file` path field. Then fit the source to the entire screen.

2. Setup OBS python script. You will need [python 3](https://www.python.org/downloads/). Then point to its install directory in OBS. By going to Tools -> Sccripts -> Python Settings tab. Then link to the install path of python.

3. Install the dependencies used by the script. You will need [pip](https://pip.pypa.io/en/stable/installation/) for this step. Afterwards, open a terminal on the directory of the extracted files from step 1 and run `pip install -r requirements.txt`

4. Add `k-tts-obsplugin.py` into the Scripts tab of OBS scripts using the + icon.

5. Configure the script. Select the media source you created in step 2 from the dropdown list in `Media Source Name`, select a default voice you want in the list of `Select Voice`. 
    - To listen to donation events using twitch chat, enter your channel name into `Twitch Channel`, and `KofiStreamBot` into the `Kofi bot name` field. Then click the connect button below and it will start listening (if these fields are populated, it will autoconnect on startup)
    - To listen from your ko-fi overlay, copy your overlay URL from the settings and paste it in `Ko-Fi stream alerts URL` field, then click the connect button below to start listening. (if these fields are populated, it will autoconnect on startup)
    - Entering your `Ko-Fi username` will allow the script to load full messages in case the donation messages in the alerts are truncated.

# More Customization

- `Allow message to use !v to select voice` - enabling this will allow donation messages to select from any voices by including a `!v<2-3 character language code><number>`
- `Censor Text` - this is a regex to replace text with `[CENSORED]` in donation messages as they come in. To filter simple words you can use `word1|text2|bad..` and it will filter away either `word1`, `text2` or any 5 letter text starts with `bad`

# Overlay CSS:
It is recommended to keep the default css OBS provided to ensure the web source's background is transparent.

You may customize the styling of the donation alert box by applying rules to the `tts-sub` class

You may customize the color of the text that is being read or have already been read by applying these custom css rules.
```
.text-speaking {
    color: pink
}

.text-spoke {
    color: purple
}
```

You may also customize the position of the alerts using 
```
#donolist {
    margin-top: 20vh;
}
```
Where in this example the donation box will be appear 20% from the height of the screen.



