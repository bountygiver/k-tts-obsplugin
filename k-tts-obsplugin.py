import obspython as obs

from time import time_ns, time, sleep
import random
from threading import Thread
import os
import tempfile
import asyncio
import json
import re
import logging
import requests

VERSION = "1.5"

wasplaying = False
recentdonations = []

playlist = []

hotkeys = {
    "clear_playlist": "KOFI SPEAKER: Stop Sound & Clear Playlist",
    "debug_playback": "KOFI SPEAKER: Debug Playback state"
}
hk = {}
k_url_field = None
k_connect_field = None

try:
    from pyquery import PyQuery
except ModuleNotFoundError:
    obs.script_log(obs.LOG_ERROR, f"pyquery is not installed. Please installed it using pip install pyquery")

# --------- HOT KEYS -----------------------------------------
def stopSound():
    global playlist
    playlist = []
    hidesource()
    sources = obs.obs_enum_sources()
    for src in sources:
        if obs.obs_source_get_id(src) == "browser_source":
            cd = obs.calldata_create()
            obs.calldata_set_string(cd, "eventName", "obs-kofi-clear-subtitle")
            obs.proc_handler_call(obs.obs_source_get_proc_handler(src), "javascript_event", cd)
            obs.calldata_destroy(cd)
    obs.source_list_release(sources)

def debugplayback():
    source = obs.obs_get_source_by_name(CurrentSettings.sourcename)
    mediastate = obs.obs_source_media_get_state(source)
    obs.script_log(obs.LOG_DEBUG, f"Media state {CurrentSettings.sourcename}: {mediastate} time: {obs.obs_source_media_get_time(source)}/{obs.obs_source_media_get_duration(source)}")
    obs.obs_source_release(source)
  
def clear_playlist(pressed):
    if pressed:
        stopSound()

def debug_playback(pressed):
    if pressed:
        debugplayback()

# ------------ WEB SCRAPPER HANDLER --------------------------
class _scrapper:
    scrapper = None
    flaresolverr_url = None
    use_flare = False

    def get(self, url):
        if self.scrapper and not self.use_flare:
            return self.scrapper.get(url).text
        if self.flaresolverr_url and self.flaresolverr_url != "":
            headers = {"Content-Type": "application/json"}
            data = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 10000
            }
            response = requests.post(self.flaresolverr_url, headers=headers, json=data)
            if response.status_code == 200:
                j = response.json()
                if j["solution"] and j["solution"]["response"]:
                    return j["solution"]["response"]
            raise f"Request failed for {url} . Please make sure you are using a valid flaresolverr endpoint."
        raise "No scrapper available"
    
    def post(self, url, data = None, headers = None):
        if self.scrapper and not self.use_flare:
            return self.scrapper.post(url, data = data, headers = headers).text
        if self.flaresolverr_url and self.flaresolverr_url != "":
            headers = {"Content-Type": "application/json"}
            data = {
                "cmd": "request.post",
                "url": url,
                "postData": data or {},
                "maxTimeout": 10000
            }
            response = requests.post(self.flaresolverr_url, headers=headers, json=data)
            if response.status_code == 200:
                j = response.json()
                if j["solution"] and j["solution"]["response"]:
                    return j["solution"]["response"]
            raise f"Request failed for {url} . Please make sure you are using a valid flaresolverr endpoint."
        raise "No scrapper available"
    
    def hasCloudScrapper(self):
        return self.scrapper is not None

    def __init__(self):
        try:
            import cloudscraper
            self.scrapper = cloudscraper.create_scraper(browser='chrome')
        except ModuleNotFoundError:
            obs.script_log(obs.LOG_ERROR, f"cloudscraper is not installed. Loading full messages may not work. Please installed it using pip install cloudscraper")
    
scrapper = _scrapper()
# ------------------------------------------------------------
async def queuesound(tts, opts):
    if tts_generator == None:
        obs.script_log(obs.LOG_ERROR,f"edge_tts is not installed! Script will not work!")
        return
    file = tempfile.NamedTemporaryFile(dir=CurrentSettings.audiofolder.name, suffix=".mp3", delete=False)
    local_pitch = "+0Hz"
    local_speed = "+0%"
    pitch_int = CurrentSettings.pitch
    speed_fl = CurrentSettings.speed - 1
    curr_voice = CurrentSettings.voice
    if CurrentSettings.commandvoice:
        matches = re.findall('(!v([\w]{2})([0-9]{0,2}))\\b', tts)
        if matches and len(matches) >= 1:
            match_voice = [f for f in CurrentSettings.voices if f["Locale"].split('-')[0].lower().startswith(matches[0][1].lower())]
            if match_voice:
                tts = tts.replace(matches[0][0], "", 1)
                idx = matches[0][2].isdigit() and int(matches[0][2]) or 0
                if idx > 0 and idx - 1 < len(match_voice):
                    curr_voice = match_voice[idx - 1]["ShortName"]
                else:
                    curr_voice = random.choice(match_voice)["ShortName"]
                    
    if opts:
        if "pitch" in opts:
            pitch_int = int(opts["pitch"])
        if "voice" in opts:
            match_voice = [v for v in CurrentSettings.voices if opts["voice"] in v["Name"]]
            if len(match_voice):
                curr_voice = match_voice[0]["ShortName"]
        if "speed" in opts:
            speed_fl = float(opts["pitch"])
    if pitch_int >= 0:
        local_pitch = f"+{pitch_int}Hz"
    elif pitch_int:
        local_pitch = f"{pitch_int}Hz"
    if speed_fl >= 1:
        local_speed = f"+{int((speed_fl - 1) * 100)}%"
    elif speed_fl > 0:
        local_speed = f"{int((1 - speed_fl) * 100)}%"

    tts = re.sub(f"\\b({CurrentSettings.censors})\\b", "[CENSORED]", tts, flags=re.IGNORECASE)
    
    communicate = tts_generator.Communicate(tts, curr_voice, pitch = local_pitch, rate = local_speed)
    subs = []
    with (
        open(file.name, "wb")
    ) as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                subs.append([chunk["offset"], chunk["duration"], chunk["text"]])
    if len(subs):
        subs.sort(key=lambda s : s[0])
    else:
        subs = [[0, 1, tts]]

    txtidx = 0
    for sub in subs:
        matchIdx = tts[txtidx:].find(sub[2])
        if matchIdx >= 0:
            startIdx = txtidx + matchIdx
            endIdx = startIdx + len(sub[2])
            sub[2] = tts[txtidx:endIdx]
            txtidx = endIdx
    if subs[-1]:
        subs[-1][2] = subs[-1][2] + tts[txtidx:]
    alert_audio = CurrentSettings.get_random_alert()
    if alert_audio:
        playlist.append((alert_audio, {}))
    playlist.append((file.name, opts, subs))
    obs.script_log(obs.LOG_DEBUG,f"Queued {tts} in {file.name}")

def matchrecentdonos(amt, sender, contents):
    t = time()
    partial_matches = [m for m in recentdonations if m[0] > t - 60 and m[1] == amt and m[2] == sender]
    for m in partial_matches:
        if (m[3] == contents):
            return True
        if len(contents) < len(m[3]) and contents.startswith(m[3]):
            return True
        if len(contents) >= len(m[3]) and m[3].startswith(contents):
            return True

    recentdonations.append((t, amt, sender, contents))
    if len(recentdonations) > 50:
        recentdonations.pop(0)
    return False

def pushdonoEvent(amt, sender, contents):
    if matchrecentdonos(amt, sender, contents):
        obs.script_log(obs.LOG_INFO,f"Repeated donation logged for {sender}: {amt} : {contents}")
    else:
        asyncio.run(queuesound(f'New {amt} donation from {sender}! {contents}', {}))

def loadFullKofiMessage(msg, donator):
    if not CurrentSettings.kofiId or scrapper == None:
        return msg
    if not CurrentSettings.kofiUId:
        try:
            u = scrapper.get(f"https://ko-fi.com/{CurrentSettings.kofiId}")
            uid = re.findall("buttonId: '(.*)?'", u)
            CurrentSettings.kofiUId = uid[0]
        except Exception as ex:
            obs.script_log(obs.LOG_WARNING, f"Unable to retrieve information for ko-fi user to load full message.")
            CurrentSettings.kofiUId = None
            return msg
    try:
        s = scrapper.get(f'https://ko-fi.com/Feed/LoadPageFeed?buttonId={CurrentSettings.kofiUId}&rt={int(time())}')
        x = PyQuery(s)
        feeditems = x('.feeditem-unit')
        for feed in feeditems:
            feedQuery = PyQuery(feed)
            donoName = feedQuery('.feeditem-poster-name').text()
            if donoName == donator:
                return feedQuery('.caption-pdg').text()
    except Exception as ex:
        obs.script_log(obs.LOG_WARNING, f"Failed to load full message from {donator}: {repr(ex)}")
    return msg

def handlekofipayload(msg):
    obs.script_log(obs.LOG_DEBUG, f"===Start handling payload {msg}===")
    rex = 'New ([0-9.]+ )?donation from (.*?)! (.*?)$'
    m = re.findall(rex, msg)
    if len(m) == 0:
        obs.script_log(obs.LOG_DEBUG, f"Regex fail for {msg}")
        if not re.match("^Visit \\w+'s Ko-fi page at:", msg) and not re.match("^Ko-fi (\\w+ )?link is:", msg) and not msg.startswith('🟩') and not msg.startswith('⬜'):
            asyncio.run(queuesound(msg, {}))
        return
    obs.script_log(obs.LOG_DEBUG, f"{m}")
    for match in m:
        obs.script_log(obs.LOG_DEBUG, f"{match}")
        if len(match) >= 3:
            amt = match[0]
            sender = match[1]
            contents = match[2].strip()
            if not contents or len(contents) > 149 or contents.endswith('""') or not contents.endswith('"'):
                sleep(2)
                obs.script_log(obs.LOG_DEBUG, f"Loading full message for {msg}")
                contents = loadFullKofiMessage(contents, sender)
            obs.script_log(obs.LOG_DEBUG, f"Pushing dono event {(amt, sender, contents)}")
            pushdonoEvent(amt, sender, contents)
        else:
            obs.script_log(obs.LOG_DEBUG, f"Not enough matching parameters for {msg}")
    obs.script_log(obs.LOG_DEBUG, f"===Finsihed handling payload===")


def handleKofiStreamAlert(msg):
    obs.script_log(obs.LOG_DEBUG, f"websocket: {msg}")
    txtmsg = msg[0]
    if len(msg) > 1 and msg[1]:
        txtmsg = msg[1]
    elif PyQuery:
        r = PyQuery(txtmsg)
        d = r('div.sa-label')
        txtmsg = d.text()
    else:
        results = re.findall('<div class=\"sa-label\">(.*)<\\/div>', txtmsg)
        if results and len(results) and results[0]:
            txtmsg = results[0]
    t = Thread(target=handlekofipayload, args=(txtmsg,))
    t.daemon = True # Daemon thread as we don't care if it completes if the application terminates
    t.start()
# ------------------------------------------------------------


def script_description():
    return "Reads a TTS message using Microsoft Natural speech synthesis\n\nQueued playback script based on script by TheAstropath"

def play_task():
    global wasplaying
    
    if not is_source_playing():
        if wasplaying:
            obs.script_log(obs.LOG_DEBUG, "Playback Done!")
            hidesource()
            wasplaying = False

        #Check to see if there is anything new to play
        if len(playlist)>0:
            sound = playlist.pop(0)
            filename = sound[0]
            opts = sound[1]
            volume = 1.0
            speed = 1.0
            current_sub = sound[2] if len(sound) >=3 else []

            if "vol" in opts:
                volume = float(opts["vol"])
            
            playsound(filename,volume,speed)
            if len(current_sub):
                sources = obs.obs_enum_sources()
                for src in sources:
                    if obs.obs_source_get_id(src) == "browser_source":
                        cd = obs.calldata_create()
                        obs.calldata_set_string(cd, "eventName", "obs-kofi-push-subtitle")
                        obs.calldata_set_string(cd, "jsonString", json.dumps({
                            "subtitle": [{
                                "offset": s[0],
                                "duration": s[1],
                                "text": s[2]
                            } for s in current_sub]
                        }))
                        obs.proc_handler_call(obs.obs_source_get_proc_handler(src), "javascript_event", cd)
                        obs.calldata_destroy(cd)
                obs.source_list_release(sources)
    else:
        wasplaying = True


def is_source_playing():
    if CurrentSettings.sourcename:
        source = obs.obs_get_source_by_name(CurrentSettings.sourcename)
        mediastate = obs.obs_source_media_get_state(source)
        time = obs.obs_source_media_get_time(source)
        duration = obs.obs_source_media_get_duration(source)
        obs.obs_source_release(source)

        return duration and time < duration and mediastate == 1   #PLAYING is 1
    return False

#==============================================================================
#
#   Settings
#
#==============================================================================
class ScriptSettings:
    def __init__(self):
        self.sourcename = ""
        self.voice = "it-IT-DiegoNeural"
        self.pitch = 0
        self.speed = 1
        self.kofiId = None
        self.kofiUId = None
        self.audiofolder = tempfile.TemporaryDirectory(ignore_cleanup_errors = True)
        self.voices = []

    def save(self, settings):
        pass

    def load(self, settings):
        sourcename              = obs.obs_data_get_string(settings, "sourcename")
        self.voice              = obs.obs_data_get_string(settings, "voicename")
        self.commandvoice       = obs.obs_data_get_bool(settings, "commandvoice")
        alert_files             = obs.obs_data_get_array(settings, "alertfile")
        self.censors            = obs.obs_data_get_string(settings, "censortext")
        self.twitchchannel      = obs.obs_data_get_string(settings, "twitchchannel")
        self.botname            = obs.obs_data_get_string(settings, "botname")
        self.speed              = obs.obs_data_get_double(settings, "speed")
        self.pitch              = obs.obs_data_get_int(settings, "pitch")
        self.kofistreamalertURL = obs.obs_data_get_string(settings, "kofistreamalertURL")
        self.testmessage = obs.obs_data_get_string(settings, "testmessage")
        new_kofi_id             = obs.obs_data_get_string(settings, "kofiId")
        if new_kofi_id != self.kofiId:
            self.kofiId = new_kofi_id
            self.kofiUId = None

        self.flaresolverr_url   = obs.obs_data_get_string(settings, "flaresolverr_url")
        self.use_flare          = not scrapper.hasCloudScrapper() or obs.obs_data_get_bool(settings, "use_flaresolverr")
        if self.sourcename != sourcename:
            hidesource()
            unsetfilename()
            self.sourcename = sourcename

        scrapper.flaresolverr_url = self.flaresolverr_url
        scrapper.use_flare = self.use_flare

        
        if alert_files:
            self.alert_files = []
            sz = obs.obs_data_array_count(alert_files)
            while sz > 0:
                sz -= 1
                arr_item = obs.obs_data_array_item(alert_files, sz)
                filename = obs.obs_data_get_string(arr_item, "value")
                if os.path.exists(filename):
                    self.alert_files.append(filename)
                obs.obs_data_release(arr_item)
            obs.obs_data_array_release(alert_files)

    def get_random_alert(self):
        if self.alert_files and len(self.alert_files):
            return random.choice(self.alert_files)
        
        
    async def populateVoices(self, tts):
        try:
            self.voices = await tts.list_voices()
        except Exception:
            obs.script_log(obs.LOG_ERROR, "Failed to load voices!")

#==============================================================================
#
#   Background Threads / Connection Handler
#
#==============================================================================
class WebscoketConnector:
    class WebSocketListener:
        def __init__(self, hub_connection_builder, target_url, callback):
            self.hub_connection_builder = hub_connection_builder
            self.url = target_url
            self.callback = callback
            self.hub_connection = None

        def connect(self):
            if not scrapper.scrapper or scrapper.use_flare:
                obs.script_log(obs.LOG_WARNING, f"Cannot connect to kofi webstream using flaresolverr")
                return
            if self.hub_connection:
                obs.script_log(obs.LOG_WARNING, f"WebSocketListener already connected before, please re-initialize a new one")
                return
            s = scrapper.get(self.url)
            negotiate = re.findall("/api/streamalerts/negotiation-token\\?userKey=[^\"]+", s)
            negotiate_token = re.findall("`(.*negotiate\\?negotiationToken.*?)`", s)
            headers = re.findall("headers: (.*)", s)
            r = scrapper.post("https://ko-fi.com" + negotiate[0])
            token_response = json.loads(r)
            r = scrapper.post(negotiate_token[0].replace('${response.token}', token_response["token"]), headers=json.loads(headers[0].replace("'", '"')))
            handshake = json.loads(r)
            self.hub_connection = self.hub_connection_builder()\
            .with_url(handshake["url"], options={
                        "access_token_factory": lambda : handshake['accessToken'],
                        "headers": {
                            "mycustomheader": "mycustomheadervalue"
                        }
                    })\
            .configure_logging(logging.ERROR)\
            .with_automatic_reconnect({
                "type": "raw",
                "keep_alive_interval": 10,
                "reconnect_interval": 5,
                "max_attempts": 5
            }).build()

            self.hub_connection.on("newStreamAlert", self.callback)
            def _close():
                self.connected = False
            def _open():
                self.connected = True
            self.hub_connection.on_close(_close)
            self.hub_connection.on_open(_open)
            self.hub_connection.start()
            obs.script_log(obs.LOG_INFO, "Ko-Fi connected")
            self.connected = True
            while self.connected:
                pass
            self.hub_connection.stop()
            obs.script_log(obs.LOG_INFO, "Ko-Fi connection closed")

        def close(self):
            if self.hub_connection:
                self.hub_connection.stop()

    def __init__(self):
        self.listener = None
        try:
            from signalrcore.hub_connection_builder import HubConnectionBuilder
            self.hub_connection_builder = HubConnectionBuilder
        except ModuleNotFoundError:
            obs.script_log(obs.LOG_ERROR, f"signalrcore or cloudscraper is not installed. Please installed it using pip install signalrcore cloudscraper")

    def connect(self, url):
        self.close_all()
        if not self.can_use():
            obs.script_log(obs.LOG_ERROR, f"signalrcore or cloudscraper is not installed. Please installed it using pip install signalrcore cloudscraper")
            return
        
        if not url:
            obs.script_log(obs.LOG_ERROR, f"Cannot connect to ko-fi without a valid URL!")
            return
        self.listener = self.WebSocketListener(self.hub_connection_builder, url, handleKofiStreamAlert)
        kofithread = Thread(target=self.listener.connect)
        kofithread.daemon = True
        kofithread.start()

    def close_all(self):
        if self.listener != None:
            self.listener.close()

    def can_use(self):
        return self.hub_connection_builder != None

class TwitchConnector:
    class TwitchListener:
        def __init__(self, twitch_chat_irc, channel_name, callback):
            self.twitch_chat_irc = twitch_chat_irc
            self.channel_name = channel_name
            self.callback = callback
            self.twitchconnection = None
            self.reconnect_max = 5
            self.reconnect_attempt = 0
        
        def start_listen(self):
            if not self.channel_name:
                obs.script_log(obs.LOG_ERROR, "Cannot connect to twitch without a channel name")
                return
            
            if self.twitchconnection:
                obs.script_log(obs.LOG_WARNING, f"Twitch connection already connected before, please re-initialize a new one")
                return
            
            self.twitchconnection = self.twitch_chat_irc.TwitchChatIRC()
            obs.script_log(obs.LOG_DEBUG, f"Connected to twitch chat: {self.channel_name}")
            try:
                self.connected = True
                self.twitchconnection.listen(self.channel_name, on_message=self.callback)
            except OSError:
                obs.script_log(obs.LOG_ERROR, "Twitch connection is no longer listening due to socket error")
            finally:
                obs.script_log(obs.LOG_INFO, "Twitch connection closed!")
                self.connected = False

            self.reconnect_attempt = self.reconnect_attempt + 1
            sleep(5 * self.reconnect_attempt)
            if self.reconnect_attempt <= self.reconnect_max:
                obs.script_log(obs.LOG_INFO, f"Attempting to reconnect to twitch...  ({self.reconnect_attempt}/{self.reconnect_max})")
                self.twitchconnection = None
                self.start_listen()

        def close(self):
            self.reconnect_attempt = self.reconnect_max + 1
            if self.twitchconnection and self.connected:
                obs.script_log(obs.LOG_DEBUG, f"Closing twitch connection...")
                self.twitchconnection.close_connection()
                self.connected = False

    def __init__(self):
        self.listener = None
        try:
            from twitch_chat_irc import twitch_chat_irc
            self.twitch_irc = twitch_chat_irc
        except ModuleNotFoundError:
            self.twitch_irc = None
            obs.script_log(obs.LOG_ERROR, f"twich_chat_irc is not installed. Please installed it using pip install twich_chat_irc")

    def connect(self, channelname):
        self.close_all()
        if not self.can_use():
            obs.script_log(obs.LOG_ERROR, f"twich_chat_irc is not installed. Cannot connect to twitch chat!")
            return
        
        if not channelname:
            obs.script_log(obs.LOG_ERROR, f"Cannot connect to twitch without a channel name!")
            return
        
        self.listener = self.TwitchListener(self.twitch_irc, channelname, twitchcallback)
        twitchthread = Thread(target = self.listener.start_listen)
        twitchthread.daemon = True
        twitchthread.start()

    def close_all(self):
        if self.listener != None:
            self.listener.close()

    def can_use(self):
        return self.twitch_irc != None
    
ws = WebscoketConnector()
twitch = TwitchConnector()
CurrentSettings = ScriptSettings()

def script_update(settings):
    CurrentSettings.load(settings)

def script_save(settings):
    for k in hotkeys.keys(): 
      a = obs.obs_hotkey_save(hk[k])
      obs.obs_data_set_array(settings, k, a)
      obs.obs_data_array_release(a)

def script_unload():
    hidesource()
    unsetfilename()
    twitch.close_all()
    ws.close_all()
    obs.script_log(obs.LOG_DEBUG, "Unloading script")
    

def hidesource():
    frontendscenes = obs.obs_frontend_get_scenes()
    for scenesource in frontendscenes:
        scene = obs.obs_scene_from_source(scenesource)
        sceneitem = obs.obs_scene_find_source(scene, CurrentSettings.sourcename)
        if sceneitem:
            obs.obs_sceneitem_set_visible(sceneitem,False)

    obs.source_list_release(frontendscenes)

def unsetfilename():
    source = obs.obs_get_source_by_name(CurrentSettings.sourcename)
    settings = obs.obs_source_get_settings(source)
    obs.obs_data_set_string(settings,"local_file","")
    obs.obs_data_set_bool(settings,"close_when_inactive",True)
    obs.obs_source_update(source,settings)
    obs.obs_data_release(settings)
    obs.obs_source_release(source)

def set_source_speed(source,speed):
    settings = obs.obs_source_get_settings(source)
    speedpct = int(speed*100)
    obs.obs_data_set_int(settings,"speed_percent",speedpct)
    obs.obs_source_update(source,settings)
    obs.obs_data_release(settings)

def playsound(filename, volume, speed):
    obs.script_log(obs.LOG_DEBUG, f"Trying to play {filename} to source {CurrentSettings.sourcename}")
    scenesource = obs.obs_frontend_get_current_scene()
    scene = obs.obs_scene_from_source(scenesource)
    sceneitem = obs.obs_scene_find_source(scene, CurrentSettings.sourcename)
    source = obs.obs_sceneitem_get_source(sceneitem)
    obs.obs_source_set_volume(source,volume)
    set_source_speed(source,speed)
    obs.obs_sceneitem_set_visible(sceneitem,False)
    settings = obs.obs_source_get_settings(source)
    obs.obs_data_set_string(settings,"local_file",filename)
    obs.obs_source_update(source,settings)
    obs.obs_sceneitem_set_visible(sceneitem,True)
    obs.obs_data_release(settings)
    obs.obs_source_release(scenesource)

async def testplayasync():
    obs.script_log(obs.LOG_DEBUG, "Hit the test play button")
    await queuesound(CurrentSettings.testmessage, {})

def testplay(props,prop):
    t = Thread(target = lambda : asyncio.run(testplayasync()))
    t.daemon = True
    t.start()

def script_defaults(settings):    
	obs.obs_data_set_default_double(settings, "speed", 1.0)
	obs.obs_data_set_default_int(settings, "pitch", 0)
	obs.obs_data_set_default_string(settings, "botname", "kofistreambot")


def populateMediaSources(lst):
    obs.obs_property_list_clear(lst)
    obs.obs_property_list_add_string(lst, "[NONE]", "")
    sources = obs.obs_enum_sources()
    for source in sources:
        if obs.obs_source_get_id(source) == "ffmpeg_source":
            name = obs.obs_source_get_name(source)
            obs.obs_property_list_add_string(lst, name, name)
    obs.source_list_release(sources)

def twitchcallback(message):
    contents = message['message']
    chatter = message['display-name']
    if chatter == CurrentSettings.botname:
        obs.script_log(obs.LOG_DEBUG, f"Bot msg: {contents}")
        handlekofipayload(contents)

def connecttwitch(props, prop):
    twitch.connect(CurrentSettings.twitchchannel)

def script_load(settings):
    obs.script_log(obs.LOG_DEBUG, "Loading script")
    hidesource()
    unsetfilename()
    obs.timer_add(play_task, 100)
    global hk

    hk["clear_playlist"] = obs.obs_hotkey_register_frontend("clear_playlist", hotkeys["clear_playlist"], lambda pressed: clear_playlist(pressed))
    a = obs.obs_data_get_array(settings, "clear_playlist")
    obs.obs_hotkey_load(hk["clear_playlist"], a)
    obs.obs_data_array_release(a)

    hk["debug_playback"] = obs.obs_hotkey_register_frontend("debug_playback", hotkeys["debug_playback"], lambda pressed: debug_playback(pressed))
    a = obs.obs_data_get_array(settings, "debug_playback")
    obs.obs_hotkey_load(hk["debug_playback"], a)
    obs.obs_data_array_release(a)

    # Load external modules
    try:
        import edge_tts
        global tts_generator
        tts_generator = edge_tts
        asyncio.run(CurrentSettings.populateVoices(tts_generator))
    except ModuleNotFoundError:
        obs.script_log(obs.LOG_ERROR, f"edge-tts is not installed. Please installed it using pip install edge-tts")

    CurrentSettings.load(settings)

    if CurrentSettings.twitchchannel and twitch.can_use():
        twitch.connect(CurrentSettings.twitchchannel)
    if CurrentSettings.kofistreamalertURL and ws.can_use():
        ws.connect(CurrentSettings.kofistreamalertURL)

    obs.script_log(obs.LOG_INFO, f"Script Loaded v {VERSION}")

def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_editable_list(props, "alertfile", "Alert Noise", obs.OBS_EDITABLE_LIST_TYPE_FILES , "*", None)
    src = obs.obs_properties_add_list(props, "sourcename", "Media Source Name", obs.OBS_COMBO_TYPE_LIST , obs.OBS_COMBO_FORMAT_STRING)
    populateMediaSources(src)
    dd = obs.obs_properties_add_list(props, "voicename", "Select Voice", obs.OBS_COMBO_TYPE_LIST , obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_properties_add_bool(props, "commandvoice", "Allow message to use !v to select voice")
    s = obs.obs_properties_add_float_slider(props, "speed", "Voice Speed", 0.25, 5.00, 0.05)
    obs.obs_property_float_set_suffix(s, "X")
    s = obs.obs_properties_add_int_slider(props, "pitch", "Voice Pitch", -100, 100, 5)
    obs.obs_property_int_set_suffix(s, "Hz")
    obs.obs_properties_add_text(props, "censortext", "Censor Text", obs.OBS_TEXT_PASSWORD)

    obs.obs_properties_add_text(props, "testmessage", "Test Message", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_button(props, "testbutton", "Test Playback", testplay)

    
    depcheck_failed = False
    
    if tts_generator:
        obs.obs_property_list_clear(dd)
        if len(CurrentSettings.voices) == 0:
            asyncio.run(CurrentSettings.populateVoices(tts_generator))
        if len(CurrentSettings.voices):
            for voice in CurrentSettings.voices:
                obs.obs_property_list_add_string(dd, voice["FriendlyName"].replace("Microsoft Server Speech Text to Speech Voice", ""), voice["ShortName"])
        else:
            obs.obs_property_list_add_string(dd, "[FAILED TO RETRIEVE VOICES]", "it-IT-DiegoNeural")
    else:
        e = obs.obs_properties_add_text(props, "err_0", "edge-tts not found. TTS will not work.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_ERROR)
        depcheck_failed = True

    if twitch.can_use():
        obs.obs_properties_add_text(props, "twitchchannel", "Twith Channel", obs.OBS_TEXT_DEFAULT)
        obs.obs_properties_add_text(props, "botname", "Kofi bot name", obs.OBS_TEXT_DEFAULT)
        obs.obs_properties_add_button(props, "twitchconnect", "(Re)Connect to Twitch", connecttwitch)
    else:
        e = obs.obs_properties_add_text(props, "err_1", "twich_chat_irc not found. Cannot connect to twitch chat.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_ERROR)

    obs.obs_properties_add_text(props, "kofiId", "Ko-Fi username", obs.OBS_TEXT_DEFAULT)
    if scrapper.hasCloudScrapper():
        obs.obs_properties_add_bool(props, "use_flaresolverr", "Use Flaresolverr (Not compatible with Ko-Fi stream alerts)")
    else:
        e = obs.obs_properties_add_text(props, "err_cloudscrapper", "Cloudscrapper not installed, you must enter a valid flaresolverr URL", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)
        scrapper.use_flare = True
    obs.obs_properties_add_text(props, "flaresolverr_url", "Flaresolverr URL", obs.OBS_TEXT_DEFAULT)
    if ws.can_use() and scrapper.hasCloudScrapper():
        global k_url_field, k_connect_field
        k_url_field = obs.obs_properties_add_text(props, "kofistreamalertURL", "Ko-Fi stream alerts URL", obs.OBS_TEXT_DEFAULT)
        k_connect_field = obs.obs_properties_add_button(props, "koficonnect", "(Re)Connect to Ko-Fi", lambda x,y: ws.connect(CurrentSettings.kofistreamalertURL))
    else:
        obs.script_log(obs.LOG_ERROR, f"signalrcore/cloudscraper is not installed. Please installed it using pip install signalrcore cloudscraper")
        e = obs.obs_properties_add_text(props, "err_2", "SignalRCore or cloudscraper not found. Cannot listen to ko-fi donation events.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)
        depcheck_failed = True

    if not PyQuery:
        e = obs.obs_properties_add_text(props, "err_3", "PyQuery not found. Cannot listen to ko-fi donation events.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)

    if depcheck_failed:
        obs.script_log(obs.LOG_ERROR, "Please install the missing dependencies.")
        e = obs.obs_properties_add_text(props, "err_summ", "Dependencies not installed. Plugin will not work correctly", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)
    
    return props