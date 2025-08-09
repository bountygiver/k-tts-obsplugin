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

VERSION = "1.4"

sourcename = ""
audiofolder = ""
testmsg = ""
alertfile = []
censors = ""
botname = ""
voice = "it-IT-DiegoNeural"
commandvoice = False
kofistreamalertURL = ""
pitch = 0
speed = 1.0
twitchchannel = ""
kofiId = ""
kofiUId = None

twitchthread = None
twitchconnection = None
kofithread = None

wasplaying = False
recentdonations = []

playlist = []
tempfiles = []
voices = []
current_sub = []
sub_time = 0

hotkeys = {
    "clear_playlist": "KOFI SPEAKER: Stop Sound & Clear Playlist",
    "debug_playback": "KOFI SPEAKER: Debug Playback state"
}
hk = {}
k_url_field = None
k_connect_field = None

# --------- HOT KEYS -----------------------------------------
def stopSound():
    global playlist
    global current_sub
    current_sub = []
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
    source = obs.obs_get_source_by_name(sourcename)
    mediastate = obs.obs_source_media_get_state(source)
    obs.script_log(obs.LOG_DEBUG, f"Media state {sourcename}: {mediastate} time: {obs.obs_source_media_get_time(source)}/{obs.obs_source_media_get_duration(source)}")
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
    global playlist
    global tempfiles
    global voice
    global commandvoice
    global speed
    global pitch
    global voices
    global alertfile
    file = tempfile.NamedTemporaryFile(dir=audiofolder.name, suffix=".mp3", delete=False)
    tempfiles.append(file)
    local_pitch = "+0Hz"
    local_speed = "+0%"
    pitch_int = pitch
    speed_fl = speed - 1
    curr_voice = voice
    if commandvoice:
        matches = re.findall('(!v([\w]{2})([0-9]{0,2}))\\b', tts)
        if matches and len(matches) >= 1:
            match_voice = [f for f in voices if f["Locale"].split('-')[0].lower().startswith(matches[0][1].lower())]
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
            match_voice = [v for v in voices if opts["voice"] in v["Name"]]
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

    global censors
    tts = re.sub(f"\\b({censors})\\b", "[CENSORED]", tts, flags=re.IGNORECASE)
    
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
    if alertfile and len(alertfile):
        playlist.append((random.choice(alertfile), {}))
    playlist.append((file.name, opts, subs))
    obs.script_log(obs.LOG_DEBUG,f"Queued {tts} in {file.name}")

def matchrecentdonos(amt, sender, contents):
    t = time()
    global recentdonations
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
    global kofiId
    global kofiUId
    if not kofiId or scrapper == None:
        return msg
    if not kofiUId:
        try:
            u = scrapper.get(f"https://ko-fi.com/{kofiId}")
            uid = re.findall("buttonId: '(.*)?'", u)
            kofiUId = uid[0]
        except Exception as ex:
            obs.script_log(obs.LOG_WARNING, f"Unable to retrieve information for ko-fi user to load full message.")
            kofiUId = None
            return msg
    try:
        s = scrapper.get(f'https://ko-fi.com/Buttons/LoadPageFeed?buttonId={kofiUId}&rt={int(time())}')
        x = pq(s)
        feeditems = x('.feeditem-unit')
        for feed in feeditems:
            feedQuery = pq(feed)
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
    elif pq:
        r = pq(txtmsg)
        d = r('div.sa-label')
        txtmsg = d.text()
    else:
        results = re.findall('<div class=\"sa-label\">(.*)<\\/div>', txtmsg)
        if results and len(results) and results[0]:
            txtmsg = results[0]
    Thread(target=handlekofipayload, args=(txtmsg,)).start()
# ------------------------------------------------------------


def script_description():
    return "Reads a TTS message using Microsoft Natural speech synthesis\n\nQueued playback script based on script by TheAstropath"

def play_task():
    global wasplaying
    global playlist
    global current_sub
    global sub_time
    
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
            sub_time = time_ns()

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
        # if current_sub and len(current_sub):
        #     sub_elapsed = (time_ns() - sub_time) / 100
        #     if current_sub[0][0] < sub_elapsed:
        #         obs.script_log(obs.LOG_DEBUG, f"Subtitle: {current_sub.pop(0)} on {sub_elapsed}")


def is_source_playing():
    source = obs.obs_get_source_by_name(sourcename)
    mediastate = obs.obs_source_media_get_state(source)
    time = obs.obs_source_media_get_time(source)
    duration = obs.obs_source_media_get_duration(source)
    #obs.script_log(obs.LOG_DEBUG, "Media state: "+str(mediastate))
    obs.obs_source_release(source)

    return duration and time < duration and mediastate == 1   #PLAYING is 1
    

def script_update(settings):
    global sourcename
    global voice
    global commandvoice
    global testmsg
    global alertfile
    global censors
    global twitchchannel
    global speed
    global pitch
    global botname
    global kofistreamalertURL
    global kofiId
    global kofiUId

    oldsource = sourcename
    sourcename     = obs.obs_data_get_string(settings, "sourcename")
    voice       = obs.obs_data_get_string(settings, "voicename")
    commandvoice = obs.obs_data_get_bool(settings, "commandvoice")
    alert_files        = obs.obs_data_get_array(settings, "alertfile")
    censors        = obs.obs_data_get_string(settings, "censortext")
    twitchchannel        = obs.obs_data_get_string(settings, "twitchchannel")
    botname        = obs.obs_data_get_string(settings, "botname")
    speed        = obs.obs_data_get_double(settings, "speed")
    pitch        = obs.obs_data_get_int(settings, "pitch")
    kofistreamalertURL = obs.obs_data_get_string(settings, "kofistreamalertURL")
    kofiId = obs.obs_data_get_string(settings, "kofiId")
    scrapper.flaresolverr_url = obs.obs_data_get_string(settings, "flaresolverr_url")
    scrapper.use_flare = not scrapper.hasCloudScrapper() or obs.obs_data_get_bool(settings, "use_flaresolverr")
    kofiUId = None
    if alert_files:
        alertfile = []
        sz = obs.obs_data_array_count(alert_files)
        while sz > 0:
            sz -= 1
            arr_item = obs.obs_data_array_item(alert_files, sz)
            filename = obs.obs_data_get_string(arr_item, "value")
            if os.path.exists(filename):
                alertfile.append(filename)
            obs.obs_data_release(arr_item)
        obs.obs_data_array_release(alert_files)
        
    testmsg = obs.obs_data_get_string(settings, "testmessage")

    if oldsource != sourcename:
        hidesource()
        unsetfilename()

def script_save(settings):
    for k in hotkeys.keys(): 
      a = obs.obs_hotkey_save(hk[k])
      obs.obs_data_set_array(settings, k, a)
      obs.obs_data_array_release(a)

def script_unload():
    global audiofolder
    global twitchconnection
    global twitchthread
    #obs.timer_remove(server_handle)
    hidesource()
    unsetfilename()
    if  twitchconnection != None:
        twitchconnection.close_connection()
        obs.script_log(obs.LOG_DEBUG, f"Closing twitch connection...")
        if twitchthread != None:
            twitchthread.join(5)
    stopkofi()
    obs.script_log(obs.LOG_DEBUG, "Unloading script")

def stopkofi():
    global kofithread
    if kofithread:
        tmp = kofithread
        kofithread = None
        tmp.join()
    

def hidesource():
    #obs.script_log(obs.LOG_DEBUG,"Trying to hide source "+sourcename)

    frontendscenes = obs.obs_frontend_get_scenes()
    #obs.script_log(obs.LOG_DEBUG,str(frontendscenes))
    
    for scenesource in frontendscenes:
        #obs.script_log(obs.LOG_DEBUG,str(scenesource))

    #scenesource = obs.obs_frontend_get_current_scene()
        scene = obs.obs_scene_from_source(scenesource)
        #obs.script_log(obs.LOG_DEBUG,"Scene "+str(scene))

        sceneitem = obs.obs_scene_find_source(scene,sourcename)
        if sceneitem:
            #obs.script_log(obs.LOG_DEBUG,"Scene item "+str(sceneitem))

            obs.obs_sceneitem_set_visible(sceneitem,False)
    
        #obs.obs_source_release(scenesource)
    obs.source_list_release(frontendscenes)

def unsetfilename():
    source = obs.obs_get_source_by_name(sourcename)
    #obs.script_log(obs.LOG_DEBUG,"Source "+str(source))

    settings = obs.obs_source_get_settings(source)
    #obs.script_log(obs.LOG_DEBUG,str(obs.obs_data_get_json(settings)))
    obs.obs_data_set_string(settings,"local_file","")
    obs.obs_data_set_bool(settings,"close_when_inactive",True)
    #obs.script_log(obs.LOG_DEBUG,str(obs.obs_data_get_json(settings)))

    obs.obs_source_update(source,settings)
    
    obs.obs_data_release(settings)
    obs.obs_source_release(source)

def set_source_speed(source,speed):
    settings = obs.obs_source_get_settings(source)
    speedpct = int(speed*100)
    obs.obs_data_set_int(settings,"speed_percent",speedpct)
    obs.obs_source_update(source,settings)
    obs.obs_data_release(settings)

def playsound(filename,volume,speed):
    obs.script_log(obs.LOG_DEBUG,"Trying to play "+filename+" to source "+sourcename)

    scenesource = obs.obs_frontend_get_current_scene()
    scene = obs.obs_scene_from_source(scenesource)
    #obs.script_log(obs.LOG_DEBUG,"Scene "+str(scene))

    sceneitem = obs.obs_scene_find_source(scene,sourcename)
    #obs.script_log(obs.LOG_DEBUG,"Scene item "+str(sceneitem))

    source = obs.obs_sceneitem_get_source(sceneitem)

    obs.obs_source_set_volume(source,volume)
    set_source_speed(source,speed)
    
    obs.obs_sceneitem_set_visible(sceneitem,False)

    settings = obs.obs_source_get_settings(source)
    #obs.script_log(obs.LOG_DEBUG,str(obs.obs_data_get_json(settings)))
    obs.obs_data_set_string(settings,"local_file",filename)
    #obs.script_log(obs.LOG_DEBUG,str(obs.obs_data_get_json(settings)))

    obs.obs_source_update(source,settings)
    
    obs.obs_sceneitem_set_visible(sceneitem,True)
    
    obs.obs_data_release(settings)
    obs.obs_source_release(scenesource)

    #obs.script_log(obs.LOG_DEBUG,"Should be visible now...")

async def testplayasync():
    global tempfiles
    global voice
    global testmsg
    global alertfile
    global playlist
    obs.script_log(obs.LOG_DEBUG, "Hit the test play button")
    await queuesound(testmsg, {})

def testplay(props,prop):
    asyncio.run(testplayasync())

def script_defaults(settings):    
	obs.obs_data_set_default_double(settings, "speed", 1.0)
	obs.obs_data_set_default_int(settings, "pitch", 0)
	obs.obs_data_set_default_string(settings, "botname", "kofistreambot")

async def populateVoices(tts, lst):
    global voices
    obs.obs_property_list_clear(lst)
    try:
        voices = await tts.list_voices()
        for voice in voices:
            obs.obs_property_list_add_string(lst, voice["FriendlyName"].replace("Microsoft Server Speech Text to Speech Voice", ""), voice["ShortName"])
    except Exception:
        obs.obs_property_list_add_string(lst, "[FAILED TO RETRIEVE VOICES]", "it-IT-DiegoNeural")

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
    global botname
    contents = message['message']
    chatter = message['display-name']
    if chatter == botname:
        obs.script_log(obs.LOG_DEBUG, f"Bot msg: {contents}")
        handlekofipayload(contents)

def twitchtask():
    global twitchconnection
    global twitchchannel
    global twitchthread
    global twitch_irc
    if twitch_irc != None and twitchchannel:
        twitchconnection = twitch_irc.TwitchChatIRC()
        obs.script_log(obs.LOG_DEBUG, f"Connected to twitch chat: {twitchchannel}")
        try:
            twitchconnection.listen(twitchchannel, on_message=twitchcallback)
        except OSError:
            obs.script_log(obs.LOG_ERROR, "Twitch connection is no longer listening due to socket error")
        finally:
            obs.script_log(obs.LOG_INFO, "Twitch connection closed!")
            twitchconnection = None

def connecttwitch(props,prop):
    global twitchthread
    if twitchconnection != None:
        twitchconnection.close_connection()
        obs.script_log(obs.LOG_DEBUG, f"Closing twitch connection...")
        if twitchthread != None:
            twitchthread.join(5)
    twitchthread = Thread(target = twitchtask)
    twitchthread.start()


def script_load(settings):
    global audiofolder
    audiofolder = tempfile.TemporaryDirectory(ignore_cleanup_errors = True)
    obs.script_log(obs.LOG_DEBUG, "Loading script")
    hidesource()
    unsetfilename()
    #obs.timer_add(server_handle,100)
    obs.timer_add(play_task,100)
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
    except ModuleNotFoundError:
        obs.script_log(obs.LOG_ERROR, f"edge-tts is not installed. Please installed it using pip install edge-tts")

    scrapper.flaresolverr_url = obs.obs_data_get_string(settings, "flaresolverr_url")
    scrapper.use_flare = obs.obs_data_get_bool(settings, "use_flaresolverr")
        
    try:
        from twitch_chat_irc import twitch_chat_irc
        global twitch_irc
        twitch_irc = twitch_chat_irc
        global twitchchannel
        twitchchannel = obs.obs_data_get_string(settings, "twitchchannel")
        if twitchchannel:
            connecttwitch(None, None)
    except ModuleNotFoundError:
        obs.script_log(obs.LOG_ERROR, f"twich_chat_irc is not installed. Please installed it using pip install twich_chat_irc")
    try:
        from signalrcore.hub_connection_builder import HubConnectionBuilder
        global ws
        def _ws_connect():
            if not scrapper.scrapper or scrapper.use_flare:
                obs.script_log(obs.LOG_WARNING, f"Cannot connect to kofi webstream using flaresolverr")
                return
            global kofistreamalertURL
            s = scrapper.get(kofistreamalertURL)
            negotiate = re.findall("/api/streamalerts/negotiation-token\\?userKey=[^\"]+", s)
            negotiate_token = re.findall("`(.*negotiate\\?negotiationToken.*?)`", s)
            headers = re.findall("headers: (.*)", s)
            r = scrapper.post("https://ko-fi.com" + negotiate[0])
            token_response = json.loads(r)
            r = scrapper.post(negotiate_token[0].replace('${response.token}', token_response["token"]), headers=json.loads(headers[0].replace("'", '"')))
            handshake = json.loads(r)
            hub_connection = HubConnectionBuilder()\
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

            hub_connection.on("newStreamAlert", handleKofiStreamAlert)
            connected = True
            def disconnect():
                obs.script_log(obs.LOG_ERROR, "Ko-Fi disconnected by peer")
                nonlocal connected
                connected = False
            hub_connection.on_close(disconnect)
            hub_connection.on_error(disconnect)
            hub_connection.start()
            obs.script_log(obs.LOG_INFO, "Ko-Fi connected")
            global kofithread
            while kofithread is not None and connected:
                pass
            hub_connection.stop()
            obs.script_log(obs.LOG_INFO, "Ko-Fi connection closed")
        def ws_connect():
            stopkofi()
            global kofithread
            kofithread = Thread(target=_ws_connect)
            kofithread.start()

        ws = ws_connect
        global kofistreamalertURL
        kofistreamalertURL = obs.obs_data_get_string(settings, "kofistreamalertURL")
        if kofistreamalertURL:
            ws()
    except ModuleNotFoundError:
        obs.script_log(obs.LOG_ERROR, f"signalrcore or cloudscraper is not installed. Please installed it using pip install signalrcore cloudscraper")

    try:
        from pyquery import PyQuery
        global pq
        pq = PyQuery
    except ModuleNotFoundError:
        obs.script_log(obs.LOG_ERROR, f"pyquery is not installed. Please installed it using pip install pyquery")
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
        asyncio.run(populateVoices(tts_generator, dd))
    else:
        e = obs.obs_properties_add_text(props, "err_0", "edge-tts not found. TTS will not work.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_ERROR)
        depcheck_failed = True

    if twitch_irc:
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
    if ws and scrapper.hasCloudScrapper():
        global k_url_field, k_connect_field
        k_url_field = obs.obs_properties_add_text(props, "kofistreamalertURL", "Ko-Fi stream alerts URL", obs.OBS_TEXT_DEFAULT)
        k_connect_field = obs.obs_properties_add_button(props, "koficonnect", "(Re)Connect to Ko-Fi", lambda x,y: ws())
    else:
        obs.script_log(obs.LOG_ERROR, f"signalrcore/cloudscraper is not installed. Please installed it using pip install signalrcore cloudscraper")
        e = obs.obs_properties_add_text(props, "err_2", "SignalRCore or cloudscraper not found. Cannot listen to ko-fi donation events.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)
        depcheck_failed = True

    if not pq:
        e = obs.obs_properties_add_text(props, "err_3", "PyQuery not found. Cannot listen to ko-fi donation events.", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)

    if depcheck_failed:
        obs.script_log(obs.LOG_ERROR, "Please install the missing dependencies.")
        e = obs.obs_properties_add_text(props, "err_summ", "Dependencies not installed. Plugin will not work correctly", obs.OBS_TEXT_INFO)
        obs.obs_property_text_set_info_type(e, obs.OBS_TEXT_INFO_WARNING)
    
    return props