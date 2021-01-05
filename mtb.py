#!/usr/bin/python
# -*- coding: utf-8 -*-

import praw,urllib,http.cookiejar,re,logging,logging.handlers,datetime,requests,requests.auth,sys,json,unicodedata
import prawcore.exceptions as praw_exception
from collections import Counter
from itertools import groupby
from time import sleep
from bs4 import BeautifulSoup

# TO DO: 
#  cookielib to http.cookiejar
# use goal.com to bypass thread request
# switch from urllib2 to requests maybe
# deal with incorrect matching of non-existent game (eg using "City", etc) - ie better way of finding matches (nearest neighbour?)
# more robust handling of errors

# every minute, check mail, create new threads, update all current threads

# browser header (to avoid 405 error with goal.com, streaming sites)
hdr = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
       'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
       'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
       'Accept-Encoding': 'none',
       'Accept-Language': 'en-US,en;q=0.8',
       'Connection': 'keep-alive'}

activeThreads = []
notify = False
messaging = True

# naughty list                                
usrblacklist = ['dbawbaby',
                '12F12',
                'KYAmiibro']

# allowed to make multiple threads, me and r/scottishfootball mods
usrwhitelist = ['mf__4', 'sfmatchthreadder'
                'dodidodidodidodi', 'That_Naked_Guy', 'cptEs', 'Tito1872', 'cammymd',
                'Bo98', 'MrMaggot98', 'methylated_spirit', 'D6P6', 'GreenLightDistrictJP']

# markup constants
goal=0;pgoal=1;ogoal=2;mpen=3;yel=4;syel=5;red=6;subst=7;subo=8;subi=9;strms=10;lines=11;evnts=12

# adjust time limit in given subreddit
custTimeLimit = {'sfmatchthreads': [10]}

# no time limit to when user can post in specific subreddit
timewhitelist = {'sfmatchthreads': ['mf__4']}
# timewhitelist = {}
def getTimestamp():
    day = str(datetime.datetime.now().day) if len(str(datetime.datetime.now().day)) > 1 else '0' + str(datetime.datetime.now().day)
    month = str(datetime.datetime.now().month) if len(str(datetime.datetime.now().month)) > 1 else '0' + str(datetime.datetime.now().month)
    year = str(datetime.datetime.now().year) if len(str(datetime.datetime.now().year)) != 4 else str(datetime.datetime.now().year)[-2:]

    dt = day + '/' + month + '/' + year + ' '
    hr = str(datetime.datetime.now().hour) if len(str(datetime.datetime.now().hour)) > 1 else '0' + str(datetime.datetime.now().hour)
    min = str(datetime.datetime.now().minute) if len(str(datetime.datetime.now().minute)) > 1 else '0' + str(datetime.datetime.now().minute)
    sec = str(datetime.datetime.now().second) if len(str(datetime.datetime.now().second)) > 1 else '0' + str(datetime.datetime.now().second)
    t = '[' + hr + ':' + min + ':' + sec + '] '
    return dt + t

def setup():
    try:
        log_information("Reddit details from argv are {}".format(tuple(sys.argv[1:9])),
                        level=logging.DEBUG)
        admin,username,password,subreddit,user_agent,id,secret,redirect = tuple(sys.argv[1:9])

        log_information("ADMIN: {}".format(admin),
                        level=logging.DEBUG)
        r = praw.Reddit(client_id=id, client_secret=secret, username=username, password=password, user_agent=user_agent)
        return r,admin,username,password,subreddit,user_agent,id,secret,redirect
    except:
        log_information("Setup error: please ensure environment variables exists in its correct form (check readme for more info)",
                        level=logging.CRITICAL)
        sleep(10)

# deprecated                
def OAuth_login():
    try:
        client_auth = requests.auth.HTTPBasicAuth( id, secret )
        headers = { 'user-agent': user_agent }
        post_data = { "grant_type": "password", "username": username, "password": password }
        response = requests.post( "https://www.reddit.com/api/v1/access_token",auth = client_auth,data = post_data,headers = headers)
        token_data = response.json( )
        all_scope = set(['identity','edit','flair','history','mysubreddits','privatemessages','read','save','submit','vote','wikiread'])
        r.set_access_credentials( all_scope, token_data[ 'access_token' ])
        log_information("OAuth session opened as /u/" + r.get_me().name,
                        level=logging.INFO)
    except:
        log_information("OAuth error, check log file",
                        level=logging.CRITICAL)
        sleep(10)

# save activeThreads
def saveData():
    f = open('bot_files/active_threads.txt', 'w+')
    s = ''
    log_information("Saving active threads data",
                    level=logging.INFO)
    for data in activeThreads:
        matchID,t1,t2,thread_id,reqr,sub = data
        if type(reqr) is not str:
            reqr = reqr.name
        s += matchID + '####' + t1 + '####' + t2 + '####' + thread_id + '####' + reqr + '####' + sub + '&&&&'
    s = s[0:-4]  # take off last &&&&
    f.write(s)
    f.close()

# read saved activeThreads data        
def readData():
    log_information("Reading in active threads from file",
                    level=logging.INFO)
    f = open('bot_files/active_threads.txt', 'r')
    s = f.read()
    log_information("Active threads read in from file is: {}".format(s),
                    level=logging.INFO)
    info = s.split('&&&&')
    if info[0] != '':
        for d in info:
            [matchID,t1,t2,thread_id,reqr,sub] = d.split('####')
            data = matchID, t1, t2, thread_id, reqr, sub
            activeThreads.append(data)
            log_information("Active threads: {} - added {} vs {} (/r/{})"
                            "".format(str(len(activeThreads)), t1, t2, sub),
                            level=logging.INFO)
    f.close()

def resetAll():
    removeList = list(activeThreads)
    for data in removeList:
        activeThreads.remove(data)
        log_information("Active threads: {} - removed {} vs {} (/r/{})"
                        "".format(str(len(activeThreads)), data[1], data[2], data[5]),
                        level=logging.INFO)
        saveData()

def loadMarkup(subreddit):
    try:
        markup = [line.rstrip('\n') for line in open(subreddit + '.txt')]
    except:
        markup = [line.rstrip('\n') for line in open('soccer.txt')]
    return markup

def getRelatedSubreddits():
    subs = []
    # main sub
    subs.append(u'scottishfootball')
    subs.append(u'SFMatchThreads')  # my test

    # premiership subreddits
    subs.append(u'rangersfc')
    subs.append(u'celticfc')
    subs.append(u'aberdeenfc')
    subs.append(u'hibsfc')
    subs.append(u'hibsfc')
    subs.append(u'killie')
    subs.append(u'dundeeunited')
    subs.append(u'stjohnstone')
    subs.append(u'motherwellfc')

    # championship
    subs.append(u'heartofmidlothianfc')
    subs.append(u'raithrovers')
    subs.append(u'pars')
    subs.append(u'ictfc')
    subs.append(u'thedarkblues')

    # league 1
    subs.append(u'falkirkfc')
    subs.append(u'clydefc')
    subs.append(u'partickthistlefc')

    # league 2
    subs.append(u'edinburghcityfc')
    subs.append(u'cowdenbeathfc')

    subs = [x.lower() for x in subs]
    return subs


def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)])

def guessRightMatch(possibles):
    matchOn = []
    for matchID in possibles:
        status = getStatus(matchID)
        if len(status) > 0:
            matchOn.append(status[0].isdigit())
        else:
            matchOn.append(False)
    stati_int = [int(elem) for elem in matchOn]
    if sum(stati_int) == 1:
        guess = possibles[stati_int.index(1)]
    else:
        guess = possibles[0]
    return guess


def writeLineUps(sub, body, t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub):
    markup = loadMarkup(sub)
    t1sprite = ''
    t2sprite = ''

    body += '**LINE-UPS**\n\n**' + t1sprite + t1 + '**\n\n'
    linestring = ''
    for name in team1Start:
        if '!sub' in name:
            linestring += ' (' + markup[subst] + name[5:] + ')'
        else:
            linestring += ', ' + name
    linestring = linestring[2:] + '.\n\n'
    body += linestring + '**Subs:** '
    body += ", ".join(x for x in team1Sub) + ".\n\n^____________________________\n\n"

    body += '**' + t2sprite + t2 + '**\n\n'
    linestring = ''
    for name in team2Start:
        if '!sub' in name:
            linestring += ' (' + markup[subst] + name[5:] + ')'
        else:
            linestring += ', ' + name
    linestring = linestring[2:] + '.\n\n'
    body += linestring + '**Subs:** '
    body += ", ".join(x for x in team2Sub) + "."

    return body

def findBBCSiteSingle(team1, team2):
    # search for each word in each team name in the fixture list, return most frequent result
    log_information("Finding BBC site for {} vs {}...".format(team1, team2),
                    level=logging.INFO)
    allTeams = {}
    try:
        linkList = []
        fixAddress = "https://www.bbc.co.uk/sport/football/scores-fixtures"
        fixWebsite = requests.get(fixAddress, timeout=15, stream=True)
        fix_html = fixWebsite.text


        html = BeautifulSoup(fix_html, 'html.parser')


        possible = []

        all_leagues = html.find_all("div", {"class": "qa-match-block"})
        for league in all_leagues:
            games = league.find_all('li')
            for game in games:
                if "Match postponed".lower() in game.text.lower():
                    log_information("Match {} Postponed, skipping".format(game.text),
                                    level=logging.DEBUG)
                    continue
                teams = game.find_all("span", {"class": 'sp-c-fixture__team-name-wrap'})
                home = teams[0].find("span")
                away = teams[1].find("span")
                link = game.find_all("a", href=True)
                if len(link) > 1:
                    log_information("MORE THAN ONE LINK ON BBC PAGE FOR {} vs {}".format(home.text, away.text),
                                    level=logging.ERROR)
                elif len(link) > 0:
                    link = link[0]
                else:
                    # print("SKIPPING {} vs {}. NO LINK".format(home.text, away.text))
                    continue
                matchId = re.findall("(?:[^\d]*)([\d]*)", link['href'])

                valid_ids = []
                #remove empty strings
                for match in matchId:
                    if match != '':
                        valid_ids.append(match)

                if len(valid_ids) > 1:
                    log_information("MORE THAN ONE MATCHID ON BBC PAGE FOR {} vs {}".format(home.text, away.text),
                                    level=logging.ERROR)
                else:
                    matchId = valid_ids[0]

                if home is None or away is None:
                    if teams is None:
                        log_information("BBC PAGE ERROR. TEAMS, HOME AND AWAY ARE NONE",
                                        level=logging.ERROR)
                    else:
                        log_information("BBC PAGE ERROR. HOME OR AWAY TEAM FOR {} IS NONE".format(teams.text),
                                        level=logging.ERROR)
                    continue

                allTeams[matchId] = (home.text, away.text)

                if remove_accents(team1).lower() == remove_accents(home.text).lower() and remove_accents(team2).lower() == remove_accents(away.text).lower():
                    possible.append(matchId)


                if remove_accents(team1).lower() == remove_accents(away.text).lower() and remove_accents(team2).lower() == remove_accents(home.text).lower():
                    possible.append(matchId)

        if len(possible) == 1:
            h, a = allTeams[possible[0]]
            return possible[0],h,a
        else:
            return -1,"",""
    except Exception:
        return -1,"",""
    except requests.exceptions.Timeout:
        log_information("BBC access timeout",
                        level=logging.ERROR)
        return 'no match'



def grabStats(t1, t2):
    bbcID, t1, t2 = findBBCSiteSingle(t1, t2)
    if bbcID == -1:
        log_information("FAILED TO GET STATS FOR {} vs {}".format(t1, t2),
                        level=logging.ERROR)
        return ""
    lineAddress = "https://www.bbc.co.uk/sport/live/football/{}".format(bbcID)
    lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
    line_html = lineWebsite.text

    # will happen if game isnt live anymore
    if lineWebsite.status_code == 404:
        lineAddress = "https://www.bbc.co.uk/sport/football/{}".format(bbcID)
        lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
        line_html = lineWebsite.text

    try:
        if lineWebsite.status_code == 200:
            body = '\n\n---------\n\n'
            body += '**MATCH STATS** | *via [BBC Sport]({})* | '.format(lineAddress)
            body += '*^(in testing, might not work properly)*\n\n'
            body += "||{}|{}|\n|:--|:--:|:--:|\n".format(t1, t2)
            data = []
            html = BeautifulSoup(line_html, 'html.parser')


            match_stats = html.find("div", {"class": "sp-c-football-match-stats"})
            match_stats_table = match_stats.find('dl')
            rows = match_stats_table.find_all('dl')
            for row in rows:
                heading = row.find("dt").text

                numbers = re.findall("[^\d]*(\d+)[^\d]*(\d+).*", row.text)[0]
                home, away = numbers
                # give possession a %
                if heading.lower() == "Possession".lower():
                    home = home + "%"
                    away = away + "%"
                data.append([heading, home, away])

            for d in data:
                body+="|"+d[0]+"|"+d[1]+"|"+d[2]+"|\n"

            # print_text("complete.")
            return body

        else:
            log_information("STATS EDIT BAD WEBPAGE STATUS CODE",
                            level=logging.WARNING)
            return ""
    except:
        log_information("STATS EDIT FAILED",
                        level=logging.WARNING)
        return ""


def grabEvents(matchID, sub):
    markup = loadMarkup(sub)
    lineAddress = "http://www.espn.com/soccer/commentary?gameId=" + matchID

    lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
    line_html = lineWebsite.text
    try:
        if lineWebsite.status_code == 200:
            body = ""
            split_all = line_html.split('<h1>Match Commentary</h1>')  # [0]:stuff [1]:commentary + key events
            split = split_all[1].split('<h1>Key Events</h1>')  # [0]:commentary [1]: key events

            events = re.findall('<tr data-id=(.*?)</tr>', split[1], re.DOTALL)
            events = events[::-1]

            # will only report goals (+ penalties, own goals), yellows, reds, subs
            supportedEvents = ['goal', 'goal---header', 'goal---free-kick', 'penalty---scored', 'own-goal',
                               'penalty---missed', 'penalty---saved', 'yellow-card', 'red-card', 'substitution']
            for text in events:
                tag = re.findall('data-type="(.*?)"', text, re.DOTALL)[0]
                if tag.lower() in supportedEvents:
                    time = re.findall('"time-stamp">(.*?)<', text, re.DOTALL)[0]
                    time = time.strip()
                    info = "**" + time + "** "
                    event = re.findall('"game-details">(.*?)</td', text, re.DOTALL)[0].strip()
                    if tag.lower().startswith('goal') or tag.lower() == 'penalty---scored' or tag.lower() == 'own-goal':
                        if tag.lower().startswith('goal'):
                            info += markup[goal] + ' **' + event + '**'
                        elif tag.lower() == 'penalty---scored':
                            info += markup[pgoal] + ' **' + event + '**'
                        else:
                            info += markup[ogoal] + ' **' + event + '**'
                    if tag.lower() == 'penalty---missed' or tag.lower() == 'penalty---saved':
                        info += markup[mpen] + ' **' + event + '**'
                    if tag.lower() == 'yellow-card':
                        info += markup[yel] + ' ' + event
                    if tag.lower() == 'red-card':
                        info += markup[red] + ' ' + event
                    if tag.lower() == 'substitution':
                        info += markup[subst] + ' ' + re.sub('<.*?>', '', event)
                    body += info + '\n\n'

            log_information("GRAB EVENTS COMPLETED",
                            level=logging.DEBUG)
            return body

        else:
            log_information("GRAB EVENTS BAD WEBPAGE STATUS CODE",
                            level=logging.ERROR)
            return ""
    except:
        log_information("GRAB EVENTS FAILED",
                        level=logging.ERROR)
        return ""

def getTimes(ko):
    hour = ko[0:ko.index(':')]
    minute = ko[ko.index(':') + 1:ko.index(':') + 3]
    hour_i = int(hour)
    min_i = int(minute)

    now = datetime.datetime.now()
    return (hour_i, min_i, now)

# attempt submission to subreddit
def submitThread(sub,title):
    log_information("Submitting {}...".format(title),
                    level=logging.INFO,
                    end='')
    try:
        thread = r.subreddit(sub).submit(title,selftext='**Venue:**\n\n**LINE-UPS**',send_replies=False)
        # thread = r.subreddit("SFMatchThreads").submit(title,selftext='**Venue:**\n\n**LINE-UPS**',send_replies=False)
        log_information("Thread ID: {} submitted for subreddit r/{}.".format(thread, sub),
                        level=logging.INFO)
        return True,thread
    except:
        log_information("SUBMIT THREAD FAILED.",
                        level=logging.CRITICAL)
        return False,''


def getLineUps(matchID):
    try:
        # try to find line-ups
        lineAddress = "http://www.espn.com/soccer/lineups?gameId=" + matchID
        lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
        line_html = lineWebsite.text
        split = line_html.split('<div class="sub-module soccer">')  # [0]:nonsense [1]:team1 [2]:team2

        if len(split) > 1:
            team1StartBlock = split[1].split('Substitutes')[0]
            if len(split[1].split('Substitutes')) > 1:
                team1SubBlock = split[1].split('Substitutes')[1]
            else:
                team1SubBlock = ''
            team2StartBlock = split[2].split('Substitutes')[0]
            if len(split[2].split('Substitutes')) > 1:
                team2SubBlock = split[2].split('Substitutes')[1]
            else:
                team2SubBlock = ''

            team1Start = []
            team2Start = []
            team1Sub = []
            team2Sub = []

            t1StartInfo = re.findall('"accordion-item" data-id="(.*?)</div>', team1StartBlock, re.DOTALL)
            t1SubInfo = re.findall('"accordion-item" data-id="(.*?)</div>', team1SubBlock, re.DOTALL)
            t2StartInfo = re.findall('"accordion-item" data-id="(.*?)</div>', team2StartBlock, re.DOTALL)
            t2SubInfo = re.findall('"accordion-item" data-id="(.*?)</div>', team2SubBlock, re.DOTALL)

            for playerInfo in t1StartInfo:
                playerInfo = playerInfo.replace('\t', '').replace('\n', '')
                playerNum = playerInfo[0:6]
                if '%' not in playerNum:
                    playertext = ''
                    if 'icon-soccer-substitution-before' in playerInfo:
                        playertext += '!sub '
                    playertext += re.findall('<span class="name">.*?data-player-uid=.*?>(.*?)<', playerInfo, re.DOTALL)[
                        0]
                    team1Start.append(playertext)
            for playerInfo in t1SubInfo:
                playerInfo = playerInfo.replace('\t', '').replace('\n', '')
                playerNum = playerInfo[0:6]
                if '%' not in playerNum:
                    playertext = ''
                    playertext += re.findall('<span class="name">.*?data-player-uid=.*?>(.*?)<', playerInfo, re.DOTALL)[
                        0]
                    team1Sub.append(playertext)
            for playerInfo in t2StartInfo:
                playerInfo = playerInfo.replace('\t', '').replace('\n', '')
                playerNum = playerInfo[0:6]
                if '%' not in playerNum:
                    playertext = ''
                    if 'icon-soccer-substitution-before' in playerInfo:
                        playertext += '!sub '
                    playertext += re.findall('<span class="name">.*?data-player-uid=.*?>(.*?)<', playerInfo, re.DOTALL)[
                        0]
                    team2Start.append(playertext)
            for playerInfo in t2SubInfo:
                playerInfo = playerInfo.replace('\t', '').replace('\n', '')
                playerNum = playerInfo[0:6]
                if '%' not in playerNum:
                    playertext = ''
                    playertext += re.findall('<span class="name">.*?data-player-uid=.*?>(.*?)<', playerInfo, re.DOTALL)[
                        0]
                    team2Sub.append(playertext)

            # if no players found:
            if team1Start == []:
                team1Start = ["*Not available*"]
            if team1Sub == []:
                team1Sub = ["*Not available*"]
            if team2Start == []:
                team2Start = ["*Not available*"]
            if team2Sub == []:
                team2Sub = ["*Not available*"]
            return team1Start, team1Sub, team2Start, team2Sub

        else:
            team1Start = ["*Not available*"]
            team1Sub = ["*Not available*"]
            team2Start = ["*Not available*"]
            team2Sub = ["*Not available*"]
            return team1Start, team1Sub, team2Start, team2Sub
    except IndexError:
        log_information("INDEX ERROR",
                        level=logging.WARNING)
        team1Start = ["*Not available*"]
        team1Sub = ["*Not available*"]
        team2Start = ["*Not available*"]
        team2Sub = ["*Not available*"]
        return team1Start, team1Sub, team2Start, team2Sub

# get current match time/status
def getStatus(matchID):
    lineAddress = "http://www.espn.com/soccer/match?gameId=" + matchID
    lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
    line_html = lineWebsite.text
    if lineWebsite.status_code == 200:
        status = re.findall('<span class="game-time".*?>(.*?)<',line_html,re.DOTALL)
        if status == []:
            return 'v'
        else:
            return status[0]
    else:
        return ''


def getTeamIDs(matchID):
    try:
        lineAddress = "http://www.espn.com/soccer/match?gameId=" + matchID
        lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
        line_html = lineWebsite.text

        teamIDs = re.findall('<div class="team-info">(.*?)</div>', line_html, re.DOTALL)
        if teamIDs != []:
            t1id = re.findall('/(?:club|team)/.*?/.*?/(.*?)"', teamIDs[0], re.DOTALL)
            t2id = re.findall('/(?:club|team)/.*?/.*?/(.*?)"', teamIDs[1], re.DOTALL)
            if t1id != []:
                t1id = t1id[0]
            else:
                t1id = ''
            if t2id != []:
                t2id = t2id[0]
            else:
                t2id = ''
            return t1id, t2id
        else:
            return '', ''
    except requests.exceptions.Timeout:
        return '', ''


def findMatchSite(team1, team2):
    # search for each word in each team name in the fixture list, return most frequent result
    log_information("Finding ESPN site for {} vs {}...".format(team1, team2),
                    level=logging.DEBUG)
    try:
        t1 = team1.split()
        t2 = team2.split()
        linkList = []
        fixAddress = "http://www.espn.com/soccer/scoreboard"
        fixWebsite = requests.get(fixAddress, timeout=15, stream=True)
        fix_html = fixWebsite.text
        matches = fix_html.split('window.espn.scoreboardData')[1]
        matches = matches.split('<body class="scoreboard')[0]
        names = matches.split('"text":"Statistics"')
        del names[-1]
        for match in names:
            check = True
            matchID = re.findall('"homeAway":.*?"href":".*?gameId=(.*?)",', match, re.DOTALL)[0][0:6]
            homeTeam = re.findall('"homeAway":"home".*?"team":{.*?"alternateColor".*?"displayName":"(.*?)"', match, re.DOTALL)
            if len(homeTeam) > 0:
                homeTeam = homeTeam[0]
            else:
                check = False
            awayTeam = re.findall('"homeAway":"away".*?"team":{.*?"alternateColor".*?"displayName":"(.*?)"', match, re.DOTALL)
            if len(awayTeam) > 0:
                awayTeam = awayTeam[0]
            else:
                check = False
            if check:
                for word in t1:
                    if remove_accents(homeTeam.lower()).find(remove_accents(word.lower())) != -1:
                        linkList.append(matchID)
                    if remove_accents(awayTeam.lower()).find(remove_accents(word.lower())) != -1:
                        linkList.append(matchID)
                for word in t2:
                    if remove_accents(homeTeam.lower()).find(remove_accents(word.lower())) != -1:
                        linkList.append(matchID)
                    if remove_accents(awayTeam.lower()).find(remove_accents(word.lower())) != -1:
                        linkList.append(matchID)
        counts = Counter(linkList)
        if counts.most_common(1) != []:
            possibles = []
            for val, grp in groupby(counts.most_common(), lambda x: x[0]):
                possibles.append(val)
                if len(possibles) > 1:
                    mode = guessRightMatch(possibles)
                else:
                    mode = possibles[0]
                log_information("Found match for {} vs {}.".format(team1, team2),
                                level=logging.DEBUG)
            return mode
        else:
            log_information("Cannot find match for {} vs {}.".format(team1, team2),
                            level=logging.WARNING)
            return 'no match'
    except requests.exceptions.Timeout:
        log_information("ESPN access timeout",
                        level=logging.WARNING)
        return 'no match'



# create a new thread using provided teams
def createNewThread(team1, team2, reqr, sub, direct):
    if direct == '':
        matchID = findMatchSite(team1, team2)
    else:
        matchID = direct
    if matchID != 'no match':
        gotinfo = False
        while not gotinfo:
            try:
                t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub, venue, ko_day, ko_time, status, comp, t1abb, t2abb = getMatchInfo(
                    matchID)
                gotinfo = True
            except requests.exceptions.Timeout:
                log_information("ESPNFC access timeout for {} vs {}.".format(team1, team2),
                                level=logging.WARNING)


        # only post to related subreddits
        relatedsubs = getRelatedSubreddits()
        if sub.lower() not in relatedsubs:
            log_information("Denied post request to /r/{} - not related".format(sub),
                            level=logging.WARNING)
            return 6, ''

        # don't post if user is blacklisted
        if reqr in usrblacklist:
            log_information("Denied post request from /u/{} - blacklisted".format(reqr),
                            level=logging.WARNING)
            return 9, ''

        # don't create a thread if the bot already made it or if user already has an active thread
        for d in activeThreads:
            matchID_at, t1_at, t2_at, id_at, reqr_at, sub_at = d
            if t1 == t1_at and sub == sub_at:
                log_information("Denied {} vs {} request for /r/{} - thread already exists".format(t1, t2, sub),
                                level=logging.INFO)
                return 4, id_at
            if reqr == reqr_at and reqr not in usrwhitelist:
                log_information("Denied post request from /u/{} - has an active thread request".format(reqr),
                                level=logging.WARNING)
                return 7, ''

        # don't create a thread if the match is done (probably found the wrong match) or postponed
        if status.startswith('FT') or status == 'AET' or status == 'Postponed':
            log_information("Denied {} vs {} request - match appears to be finished".format(t1, t2),
                            level=logging.INFO)
            return 3, ''

        timelimit = 5
        if sub.lower() in custTimeLimit:
            timelimit = custTimeLimit[sub.lower()][0]
        # don't create a thread more than 5 minutes before kickoff
        if type(reqr) is not str:
            reqr = reqr.name
        if sub.lower() not in timewhitelist or sub.lower() in timewhitelist and reqr.lower() not in timewhitelist[
            sub.lower()]:
            hour_i, min_i, now = getTimes(ko_time)
            now_f = now + datetime.timedelta(hours=0, minutes=timelimit)  # timezone
            log_information("Allowed Time: {}; Game Time: {}".format(now_f, ko_time),
                            level=logging.DEBUG)
            if ko_day == '':
                return 1, ''
            if now_f.day < int(ko_day):
                log_information("Denied {} vs {} request - more than {} minutes to kickoff".format(t1, t2, timelimit),
                                level=logging.INFO)
                return 2, ''
            if now_f.hour < hour_i:
                log_information("Denied {} vs {} request - more than {} minutes to kickoff".format(t1, t2, timelimit),
                                level=logging.INFO)
                return 2, ''
            if (now_f.hour == hour_i) and (now_f.minute < min_i):
                log_information("Denied {} vs {} request - more than {} minutes to kickoff".format(t1, t2, timelimit),
                                level=logging.INFO)
                return 2, ''

        # competition logic, go here to remove friendly games when i know what it looks like
        title = 'Match Thread: ' + t1 + ' vs ' + t2
        if (sub in ['matchthreaddertest', 'soccerdev2']):
            title = title + ' [' + t1abb + '-' + t2abb + ']'
        if comp != '':
            title = title + ' | ' + comp
        result, thread = submitThread(sub, title)

        # try and set the flair to "Match Thread" if possible
        try:
            flairs = thread.flair.choices()
            log_information("Available flairs are {}".format(str(flairs)),
                            level=logging.DEBUG)

            flair_id = -1
            for flair in flairs:
                if 'Match Thread'.lower() == flair['flair_text'].lower():
                    flair_id = flair['flair_template_id']

            if flair_id != -1:
                thread.flair.select(flair_id)
        except praw_exception.Forbidden:
            log_information("Flairs not allowed on this subreddit (r/{})".format(sub),
                            level=logging.INFO)
        # if subreddit was invalid, notify
        if result == False:
            return 5, ''

        short = thread.shortlink
        thread_id = short[short.index('.it/') + 4:].encode("utf8")
        t_id = re.findall("b'(.*)'", str(thread_id))[0]
        redditstream = 'http://www.reddit-stream.com/comments/' + str(t_id)


        data = matchID, t1, t2, t_id, reqr, sub

        activeThreads.append(data)
        saveData()
        log_information("Active threads: {} - added {} vs {} (/r/{})"
                        "".format(str(len(activeThreads)), t1, t2, sub),
                        level=logging.INFO)

        if status == 'v':
            status = "0'"

        markup = loadMarkup(sub)

        body = '#**' + status + ": " + t1 + ' vs ' + t2 + '**\n\n'

        body += '**Venue:** ' + venue + '\n\n'
        body += '[Auto-refreshing reddit comments link](' + redditstream + ')\n\n---------\n\n'

        body += markup[lines] + ' '
        body = writeLineUps(sub, body, t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub)

        # add stats
        body += grabStats(t1, t2)

        # "[^[Request ^a ^match ^thread]](http://www.reddit.com/message/compose/?to=SFMatchThreadder&subject=Match%20Thread&message=Team%20vs%20Team)"
        body += '\n\n------------\n\n' + markup[
            evnts] + ' **MATCH EVENTS** | *via [ESPN](http://www.espn.com/soccer/match?gameId=' + matchID + ')*\n\n'
        body += "\n\n--------\n\n*^(Don't see a thread for a match you're watching?) [^(Click here)](https://www.reddit.com/r/soccer/wiki/matchthreads#wiki_match_thread_bot) ^(to learn how to request a match thread from this bot.)*"


        thread.edit(body)
        sleep(5)

        return 0, t_id
    else:
        log_information("Could not find match info for {} vs {}".format(team1, team2),
                        level=logging.WARNING)
        return 1, ''


# get venue, ref, lineups, etc from ESPN
def getMatchInfo(matchID):
    lineAddress = "http://www.espn.com/soccer/match?gameId=" + matchID
    log_information("Finding ESPN info from {}...".format(lineAddress),
                    level=logging.DEBUG)
    lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
    line_html = lineWebsite.text

    # get "fixed" versions of team names (ie team names from ESPNFC, not team names from match thread request)
    team1fix = re.findall('<span class="long-name">(.*?)<', line_html, re.DOTALL)[0]
    team2fix = re.findall('<span class="long-name">(.*?)<', line_html, re.DOTALL)[1]
    t1id, t2id = getTeamIDs(matchID)
    t1abb, t2abb = getTeamAbbrevs(matchID)

    if team1fix[-1] == ' ':
        team1fix = team1fix[0:-1]
    if team2fix[-1] == ' ':
        team2fix = team2fix[0:-1]

    status = getStatus(matchID)
    ko_date = re.findall('<span data-date="(.*?)T', line_html, re.DOTALL)
    if ko_date != []:
        ko_date = ko_date[0]
        ko_day = ko_date[8:]
        ko_time = re.findall('<span data-date=".*?T(.*?)Z', line_html, re.DOTALL)[0]
    # above time is actually 5 hours from now (ESPN time in source code)
    else:
        ko_day = ''
        ko_time = ''

    venue = re.findall('<div>VENUE: (.*?)<', line_html, re.DOTALL)
    if venue != []:
        venue = venue[0]
    else:
        venue = '?'

    compfull = re.findall('<div class="game-details header">(.*?)<', line_html, re.DOTALL)
    if compfull != []:
        comp = re.sub('20.*? ', '', compfull[0]).strip(' \n\t\r')
        if comp.find(',') != -1:
            comp = comp[0:comp.index(',')]
    else:
        comp = ''

    team1Start, team1Sub, team2Start, team2Sub = getLineUps(matchID)
    log_information("Match info gathered for {} vs {}.".format(t1abb, t2abb),
                    level=logging.DEBUG)
    return (
    team1fix, t1id, team2fix, t2id, team1Start, team1Sub, team2Start, team2Sub, venue, ko_day, ko_time, status, comp,
    t1abb, t2abb)


def getTeamAbbrevs(matchID):
    lineAddress = "http://www.espn.com/soccer/match?gameId=" + matchID
    lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
    line_html = lineWebsite.text

    t1abb = re.findall('<span class="long-name">(.*?)<', line_html, re.DOTALL)[0][0:3].upper()
    t2abb = re.findall('<span class="long-name">(.*?)<', line_html, re.DOTALL)[1][0:3].upper()

    teamabbs = re.findall('<span class="abbrev">(.*?)<', line_html, re.DOTALL)
    if len(teamabbs) >= 2:
        t1abb = teamabbs[0][0:3]
        t2abb = teamabbs[1][0:3]
    return t1abb, t2abb


# if the requester just wants a template
def createMatchInfo(team1, team2):
    matchID = findMatchSite(team1, team2)
    if matchID != 'no match':
        t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub, venue, ko_day, ko_time, status, comp, t1abb, t2abb = getMatchInfo(
            matchID)

        markup = loadMarkup('soccer')

        body = '#**' + status + ": " + t1 + ' vs ' + t2 + '**\n\n'
        body += '**Venue:** ' + venue + '\n\n--------\n\n'
        body += markup[lines] + ' '
        body = writeLineUps('soccer', body, t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub)

        body += '\n\n------------\n\n' + markup[evnts] + ' **MATCH EVENTS**\n\n'

        log_information("Created template for " + t1 + " vs " + t2,
                        level=logging.INFO)
        return 0, body
    else:
        return 1, ''


# delete a thread (on admin request)
def deleteThread(id):
    try:
        if '//' in id:
            id = re.findall('comments/(.*?)/',id)[0]
        thread = r.submission(id=id)
        for data in activeThreads:
            matchID,team1,team2,thread_id,reqr,sub = data
            if thread_id == id:
                thread.delete()
                activeThreads.remove(data)
                log_information("Active threads: {} - removed {} vs {} (/r/{})"
                                "".format(str(len(activeThreads)), team1, team2, sub),
                                level=logging.INFO)
                saveData()
                return team1 + ' vs ' + team2
        return ''
    except:
        return ''

# remove incorrectly made thread if requester asks within 5 minutes of creation
def removeWrongThread(id,req):
    try:
        thread = r.submission(id = id)
        dif = datetime.datetime.utcnow() - datetime.datetime.utcfromtimestamp(thread.created_utc)
        for data in activeThreads:
            matchID,team1,team2,thread_id,reqr,sub = data
            if thread_id == id:
                if reqr != req:
                    return 'req'
                if dif.days != 0 or dif.seconds > 300:
                    return 'time'
                thread.delete()
                activeThreads.remove(data)
                log_information("Active threads: {} - removed {} vs {} (/r/{})"
                                "".format(str(len(activeThreads)), team1, team2, sub),
                                level=logging.INFO)
                saveData()
                return team1 + ' vs ' + team2
        return 'thread'
    except:
        return 'thread'

# default attempt to find teams: split input in half, left vs right        
def firstTryTeams(msg):
    t = msg.split()
    spl = int(len(t)/2)
    t1 = t[0:spl]
    t2 = t[spl+1:]
    t1s = ''
    t2s = ''
    for word in t1:
        t1s += word + ' '
    for word in t2:
        t2s += word + ' '
    return [t1s,t2s]

# check for new mail, create new threads if needed
def checkAndCreate():
    log_information("Checking inbox...",
                    level=logging.INFO)
    delims = [' x ',' - ',' v ',' vs ']
    subdel = ' for '
    for msg in r.inbox.unread(mark_read=False):
        sub = subreddit
        if msg.subject.lower() == 'match thread':
            msg.mark_read()
            subreq = msg.body.split(subdel,2)
            if subreq[0] != msg.body:
                sub = subreq[1].split('/')[-1]
                sub = sub.lower()
                sub = sub.strip()
            teams = firstTryTeams(subreq[0])
            for delim in delims:
                attempt = subreq[0].split(delim,2)
                if attempt[0] != subreq[0]:
                    teams = attempt
            # euroteams = ['italy','republic of ireland','ireland','sweden','belgium','iceland','austria','hungary','portugal','switzerland','poland','croatia','wales','germany','spain','france','england']
            # if teams[0].lower() in euroteams or teams[1].lower() in euroteams:
            # msg.reply("Sorry, this bot can't be used for Euro 2016 matches. [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you want to know how to you make your own match thread!\n\n--------------\n\n[^Why ^doesn't ^the ^bot ^work ^for ^Euro ^2016?](https://www.reddit.com/r/soccer/comments/4oun18/match_thread_switzerland_vs_france_euro_2016/d4fn9n8)")
            # print_text("Denied a Euro 2016 thread: " + msg.body)
            #else:
            threadStatus,thread_id = createNewThread(teams[0], teams[1], msg.author, sub, '')
            if messaging:
                if threadStatus == 0: # thread created successfully
                    msg.reply("[Here](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") is a link to the thread you've requested. Thanks for using this bot!\n\n-------------------------\n\n*Did I create a thread for the wrong match? [Click here and press send](http://www.reddit.com/message/compose/?to=" + username + "&subject=delete&message=" + thread_id + ") to delete the thread (note: this will only work within five minutes of the thread's creation). This probably means that I can't find the right match - sorry!*")
                    if notify:
                        message_bot("Match thread request fulfilled /u/" + msg.author.name + " requested " + teams[0] + " vs " + teams[1] + " in /r/" + sub + ". \n\nThread link: http://www.reddit.com/r/" + sub + "/comments/" + thread_id + " | Deletion link: http://www.reddit.com/message/compose/?to=" + username + "&subject=delete&message=" + thread_id)
                if threadStatus == 1: # not found
                    msg.reply("Sorry, I couldn't find info for that match. In the future I'll account for more matches around the world.\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*")
                if threadStatus == 2: # before kickoff
                    msg.reply("Please wait until at least 5 minutes to kickoff to send me a thread request, just in case someone does end up making one themselves. Thanks!\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*")
                if threadStatus == 3: # after full time - probably found the wrong match
                    msg.reply("Sorry, I couldn't find a currently live match with those teams - are you sure the match has started (and hasn't finished)? If you think this is a mistake, it probably means I can't find that match.\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*")
                if threadStatus == 4: # thread already exists
                    msg.reply("There is already a [match thread](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") for that game. Join the discussion there!")
                if threadStatus == 5: # invalid subreddit
                    msg.reply("Sorry, I couldn't post to /r/" + sub + ". It may not exist, or I may have hit a posting limit.")
                if threadStatus == 6: # sub blacklisted
                    msg.reply("Sorry, I can't post to /r/" + sub + ". Please message /u/" + admin + " if you think this is a mistake.")
                if threadStatus == 7: # thread limit
                    msg.reply("Sorry, you can only have one active thread request at a time.")
                if threadStatus == 8: # status set to red
                    msg.reply("Sorry, the bot is currently unable to post threads. Check with /u/" + admin + " for more info; this should hopefully be resolved soon.")

        if msg.subject.lower() == 'match info':
            teams = firstTryTeams(msg.body)
            for delim in delims:
                attempt = msg.body.split(delim,2)
                if attempt[0] != msg.body:
                    teams = attempt
            threadStatus,text = createMatchInfo(teams[0],teams[1])
            if threadStatus == 0: # successfully found info
                msg.reply("Below is the information for the match you've requested.\n\nIf you're using [RES](http://redditenhancementsuite.com/), you can use the 'source' button below this message to copy/paste the exact formatting code. If you aren't, you'll have to add the formatting yourself.\n\n----------\n\n" + text)
            if threadStatus == 1: # not found
                msg.reply("Sorry, I couldn't find info for that match. In the future I'll account for more matches around the world.")

        if msg.subject.lower() == 'delete':
            if msg.author == admin:
                name = deleteThread(msg.body)
                if messaging:
                    if name != '':
                        msg.reply("Deleted " + name)
                    else:
                        msg.reply("Thread not found")
            else:
                name = removeWrongThread(msg.body,msg.author)
                if messaging:
                    if name == 'thread':
                        msg.reply("Thread not found - please double-check thread ID")
                    elif name == 'time':
                        msg.reply("This thread is more than five minutes old - thread deletion from now is an admin feature only. You can message /u/" + admin + " if you'd still like the thread to be deleted.")
                    elif name == 'req':
                        msg.reply("Username not recognised. Only the thread requester and bot admin have access to this feature.")
                    else:
                        msg.reply("Deleted " + name)
    if len(activeThreads) > 0:
        log_information("All messages checked.",
                        level=logging.INFO)

def getExtraInfo(matchID):
	try:
		lineAddress = "http://www.espn.com/soccer/match?gameId=" + matchID
		lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
		line_html = lineWebsite.text
		info = re.findall('data-stat="note">(.*?)<',line_html,re.DOTALL)
		if info == []:
			return ''
		else:
			return info[0]
	except requests.exceptions.Timeout:
		return ''


# update score, scorers
def updateScore(matchID, t1, t2, sub):
    try:
        lineAddress = "http://www.espn.com/soccer/match?gameId=" + matchID
        lineWebsite = requests.get(lineAddress, timeout=15, stream=True)
        line_html = lineWebsite.text
        leftScore = re.findall('data-stat="score">(.*?)<', line_html, re.DOTALL)[0].strip()
        rightScore = re.findall('data-stat="score">(.*?)<', line_html, re.DOTALL)[1].strip()
        info = getExtraInfo(matchID)
        status = getStatus(matchID)
        ESPNUpdating = True
        if status == 'v':
            status = "0'"
            ESPNUpdating = False

        leftInfo = re.findall('<div class="team-info players"(.*?)</div>', line_html, re.DOTALL)[0]
        rightInfo = re.findall('<div class="team-info players"(.*?)</div>', line_html, re.DOTALL)[1]

        leftGoals = re.findall('data-event-type="goal"(.*?)</ul>', leftInfo, re.DOTALL)
        rightGoals = re.findall('data-event-type="goal"(.*?)</ul>', rightInfo, re.DOTALL)

        if leftGoals != []:
            leftScorers = re.findall('<li>(.*?)</li', leftGoals[0], re.DOTALL)
        else:
            leftScorers = []
        if rightGoals != []:
            rightScorers = re.findall('<li>(.*?)</li', rightGoals[0], re.DOTALL)
        else:
            rightScorers = []

        t1id, t2id = getTeamIDs(matchID)

        text = '#**' + status + ": " + t1 + ' ' + leftScore + '-' + rightScore + ' ' + t2 + '**\n\n'
        if not ESPNUpdating:
            text += '*If the match has started, ESPN might not be providing updates for this game.*\n\n'

        if info != '':
            text += '***' + info + '***\n\n'

        left = ''
        if leftScorers != []:
            left += "*" + t1 + " scorers: "
            for scorer in leftScorers:
                scorer = scorer[0:scorer.index('<')].strip(' \t\n\r') + ' ' + scorer[scorer.index('('):scorer.index(
                    '/') - 1].strip(' \t\n\r')
                left += scorer + ", "
            left = left[0:-2] + "*"

        right = ''
        if rightScorers != []:
            right += "*" + t2 + " scorers: "
            for scorer in rightScorers:
                scorer = scorer[0:scorer.index('<')].strip(' \t\n\r') + ' ' + scorer[scorer.index('('):scorer.index(
                    '/') - 1].strip(' \t\n\r')
                right += scorer + ", "
            right = right[0:-2] + "*"

        text += left + '\n\n' + right

        return text
    except requests.exceptions.Timeout:
        return '#**--**\n\n'


# update all current threads
def updateThreads():
    toRemove = []

    for data in activeThreads:
        finished = False
        index = activeThreads.index(data)
        matchID,team1,team2,thread_id,reqr,sub = data
        thread = r.submission(id=thread_id)
        body = thread.selftext

        log_information("Status for {} v {}: {}".format(team1, team2, getStatus(matchID)),
                        level=logging.DEBUG)
        venueIndex = body.index('**Venue:**')

        markup = loadMarkup(subreddit)
        # detect if finished
        if getStatus(matchID) == 'FT' or getStatus(matchID) == 'AET':
            finished = True
        elif getStatus(matchID) == 'FT-Pens' or getStatus(matchID) == 'PEN':
            info = getExtraInfo(matchID)
            log_information("INFO for {} v {}: {}".format(team1, team2, info),
                            level=logging.DEBUG)
            if 'won' in info or 'win' in info or 'advance' in info:
                finished = True

        # update lineups
        team1Start,team1Sub,team2Start,team2Sub = getLineUps(matchID)
        lineupIndex = body.index('**LINE-UPS**')
        bodyTilThen = body[venueIndex:lineupIndex]

        t1id,t2id = getTeamIDs(matchID)
        newbody = writeLineUps(sub,bodyTilThen,team1,t1id,team2,t2id,team1Start,team1Sub,team2Start,team2Sub)

        # add stats
        newbody += grabStats(team1, team2)

        newbody += '\n\n------------\n\n' + markup[
            evnts] + ' **MATCH EVENTS** | *via [ESPN](http://www.espn.com/soccer/match?gameId=' + matchID + ')*\n\n'


        # update scorelines
        score = updateScore(matchID, team1, team2, sub)
        newbody = score + '\n\n--------\n\n' + newbody

        events = grabEvents(matchID, sub)
        newbody += '\n\n' + events



        # remove strong tags that happen at own goals
        if "<strong>" in newbody or "</strong>" in newbody:
            log_information("Strong tags found. Replacing them.",
                            level=logging.DEBUG)
            newbody = newbody.replace("<strong>", "")
            newbody = newbody.replace("</strong>", "")


        # save data
        if newbody != body:
            log_information("Making edit to {} vs {} (/r/{})".format(team1, team2, sub),
                            level=logging.INFO)
            thread.edit(newbody)
            saveData()
        newdata = matchID,team1,team2,thread_id,reqr,sub
        activeThreads[index] = newdata

        if finished:
            toRemove.append(newdata)

    for getRid in toRemove:
        activeThreads.remove(getRid)
        log_information("Active threads: {} - removed {} vs {} (/r/{})"
                        "".format(str(len(activeThreads)), getRid[1], getRid[2], getRid[5]),
                        level=logging.INFO)
        saveData()

def findMatchSiteSingle(team):
    # search for each word in each team name in the fixture list, return most frequent result
    log_information("Finding ESPN site for {}...".format(team),
                    level=logging.DEBUG)

    try:
        t1 = team.split()
        linkList = []
        fixAddress = "http://www.espn.com/soccer/scoreboard"
        fixWebsite = requests.get(fixAddress, timeout=15, stream=True)
        fix_html = fixWebsite.text
        matches = fix_html.split('window.espn.scoreboardData')[1]
        matches = matches.split('<body class="scoreboard')[0]
        names = matches.split('"text":"Statistics"')
        del names[-1]
        for match in names:
            check = True
            matchID = re.findall('"homeAway":.*?"href":".*?gameId=(.*?)",', match, re.DOTALL)[0][0:6]
            homeTeam = re.findall('"homeAway":"home".*?"team":{.*?"alternateColor".*?"displayName":"(.*?)"', match, re.DOTALL)
            if len(homeTeam) > 0:
                homeTeam = homeTeam[0]
            else:
                check = False
            awayTeam = re.findall('"homeAway":"away".*?"team":{.*?"alternateColor".*?"displayName":"(.*?)"', match, re.DOTALL)
            if len(awayTeam) > 0:
                awayTeam = awayTeam[0]
            else:
                check = False
            if check:
                if remove_accents(homeTeam.lower()) == (remove_accents(team.lower())):
                    linkList.append(matchID)
                if remove_accents(awayTeam.lower()) == (remove_accents(team.lower())):
                    linkList.append(matchID)
        counts = Counter(linkList)
        if counts.most_common(1) != []:
            possibles = []
            for val, grp in groupby(counts.most_common(), lambda x: x[0]):
                possibles.append(val)
                if len(possibles) > 1:
                    mode = guessRightMatch(possibles)
                else:
                    mode = possibles[0]
            log_information("Found match for {}".format(team),
                            level=logging.INFO)
            return mode
        else:
            log_information("No match found for {}".format(team),
                            level=logging.INFO)
            return 'no match'
    except requests.exceptions.Timeout:
        log_information("ESPN access timeout",
                        level=logging.WARNING)
        return 'no match'

# r/scottishfootball games
def check_spfl_games(attempts, premiership_teams):
    attempts = attempts + 1
    log_information("r/scottishfootball - COUNT IS {}".format(attempts),
                    level=logging.INFO)

    # All teams to consider
    all_teams = ["Rangers", "Celtic", "Hibernian", "Aberdeen",
                 "Kilmarnock", "Dundee United", "Ross County", "Livingston",
                 "St Johnstone", "Motherwell", "St Mirren", "Hamilton Academical",
                 "Scotland"]

    log_information("r/scottishfootball - ALL TEAMS CONSIDERED: " + str(all_teams),
                    level=logging.DEBUG)
    active_teams = []
    # dont check for any team who's already in a thread
    for thread in activeThreads:
        _, t1, t2, _, _, sub = thread
        # only care about scottishfootball threads
        if sub == "scottishfootball":
            log_information("r/scottishfootball - FOUND ACTIVE THREAD - {} vs {}".format(t1, t2),
                            level=logging.DEBUG)
            active_teams.append(t1)
            active_teams.append(t2)
            if t1 in all_teams:
                all_teams.remove(t1)
            if t2 in all_teams:
                all_teams.remove(t2)

            if t1 in premiership_teams.keys():
                del premiership_teams[t1]
            if t2 in premiership_teams.keys():
                del premiership_teams[t2]

            log_information("r/scottishfootball - TEAMS {} & {} NO LONGER CONSIDERED".format(t1, t2),
                            level=logging.DEBUG)


    # see if any games are less than an hour away roughly every 30 mins
    if attempts >= 30:
        log_information("r/scottishfootball - CONSIDERED TEAMS: " + str(all_teams),
                        level=logging.INFO)
        attempts = 0
        for team in sorted(all_teams):
            match_id = findMatchSiteSingle(team.lower())
            if match_id != 'no match':
                # only some things matter rn
                _, _, _, _, _, _, _, _, _, _, ko_time, status, _, _, _ = getMatchInfo(match_id)

                hour_i, min_i, now = getTimes(ko_time)
                now_f = now + datetime.timedelta(hours=1, minutes=0)

                # is the game in the next hour?
                if (now_f.hour > hour_i) or ((now_f.hour == hour_i) and (now_f.minute > min_i)):
                    # is this game already being tracked / already been detected as being soon?
                    if team not in active_teams and team not in premiership_teams:
                        # is the game finished?
                        if not (status.startswith('FT') or status == 'AET'):
                            if not status == 'Postponed':
                                # store team and match id
                                premiership_teams[team] = match_id
                                message_bot("Team {} is less than an hour away from playing"
                                            "(http://www.espn.com/soccer/match?gameId={}).".format(team, match_id))

    log_information("r/scottishfootball - TEAMS TO PLAY IN NEXT HOUR: " + str(premiership_teams),
                    level=logging.INFO)
    to_remove = []
    for team in premiership_teams:
        match_id = premiership_teams[team]
        status, thread_id = createNewThread(team, "", "mf__4", "scottishfootball", match_id)
        if status == 0:
            to_remove.append(team)

            if status == 0:  # success
                message = "New Match Thread made for {}. ".format(team) + \
                "(Link to thread: http://www.reddit.com/r/scottishfootball/comments/{})".format(thread_id)
                message_bot(message)


    for added in to_remove:
        del premiership_teams[added]
    return attempts, premiership_teams

# custom subreddit games (eg rangers games for r/rangerfc, celtic games for r/celticfc)
def check_sub_games(attempts, sub_games):
    attempts = attempts + 1
    log_information("custom subreddits - COUNT is {}".format(attempts),
                    level=logging.DEBUG)

    relevant_subreddit = {"Rangers": 'SFMatchThreads',
                          "Brentford": 'SFMatchThreads'}
                 # "Celtic": u'celticfc',
                 # "Hibernian": u'hibsfc',
                 # "Aberdeen": u'aberdeenfc',
                 # "Kilmarnock": u'killie',
                 # "Dundee United": u'dundeeunited',
                 # "St Johnstone": u'stjohnstone',
                 # "Motherwell": u'motherwellfc'}

    log_information("custom subreddits - ALL TEAMS CONSIDERED: " + str(relevant_subreddit),
                    level=logging.DEBUG)
    active_teams = []
    # dont check for any team who's already in a thread
    for thread in activeThreads:
        _, t1, t2, _, _, sub = thread

        if sub != "scottishfootball":
            log_information("{} - FOUND ACTIVE THREAD - {} vs {}".format(sub, t1, t2),
                            level=logging.DEBUG)

        # is the active thread in the personal subreddit for each team?
        if t1 in relevant_subreddit.keys():
            if relevant_subreddit[t1].lower() == sub.lower():
                active_teams.append(t1)
                del relevant_subreddit[t1]
                if t1 in sub_games.keys():
                    del sub_games[t1]

                log_information("{} - TEAM {} NO LONGER CONSIDERED".format(sub, t1),
                                level=logging.DEBUG)

        if t2 in relevant_subreddit.keys():
            if relevant_subreddit[t2].lower() == sub.lower():
                active_teams.append(t2)
                del relevant_subreddit[t2]
                if t2 in sub_games.keys():
                    del sub_games[t2]

                log_information("{} - TEAM {} NO LONGER CONSIDERED".format(sub, t2),
                                level=logging.DEBUG)



    # see if any games are less than an hour away roughly every 30 mins
    if attempts >= 30:
        attempts = 0
        log_information("custom subreddits - CONSIDERED TEAMS: " + str(relevant_subreddit),
                        level=logging.INFO)
        for team in sorted(relevant_subreddit.keys()):
            match_id = findMatchSiteSingle(team.lower())
            if match_id != 'no match':
                # only some things matter rn
                _, _, _, _, _, _, _, _, _, _, ko_time, status, _, _, _ = getMatchInfo(match_id)

                hour_i, min_i, now = getTimes(ko_time)
                now_f = now + datetime.timedelta(hours=1, minutes=0)

                # is the game in the next hour?
                if (now_f.hour > hour_i) or ((now_f.hour == hour_i) and (now_f.minute > min_i)):
                    # is this game already being tracked / already been detected as being soon?
                    if team not in active_teams and team not in sub_games:
                        # is the game finished?
                        if not (status.startswith('FT') or status == 'AET'):
                            if not status == 'Postponed':
                                # store team and match id
                                sub_games[team] = match_id
                                message_bot("Team {} is less than an hour away from playing for subreddit {} "
                                            "(http://www.espn.com/soccer/match?gameId={}).".format(team, relevant_subreddit[team], match_id))

    log_information("custom subreddits - TEAMS TO PLAY IN NEXT HOUR: " + str(sub_games),
                    level=logging.INFO)

    to_remove = []
    for team in sub_games:
        match_id = sub_games[team]
        status, thread_id = createNewThread(team, "", "mf__4", relevant_subreddit[team], match_id)
        if status == 0:
            to_remove.append(team)

            if status == 0:  # success
                message = "New Match Thread made for {} in personal subreddit {}. ".format(team, relevant_subreddit[team]) + \
                          "(Link to thread: http://www.reddit.com/r/{}/comments/{})".format(relevant_subreddit[team], thread_id)
                message_bot(message)

    for added in to_remove:
        del sub_games[added]
    return attempts, sub_games


def message_bot(message):
    log_information("SENDING TELEGRAM MESSAGE: {}".format(message),
                    level=logging.INFO)
    url = "https://api.telegram.org/bot{}/sendMessage?chat_id={}&text={}".format(telegram_bot_token, telegram_owner, message)
    requests.post(url)

def log_information(message, level=logging.INFO, end="\n"):
    print(getTimestamp() + "[{}]".format(message), end=end)
    for match_threader_logger in loggers:
        match_threader_logger.log(level=level, msg=message)

    if level == logging.ERROR:
        message_bot("ERROR WITH MATCH THREADER: {}".format(message))

    if level == logging.CRITICAL:
        message_bot("CRITICAL ERROR WITH MATCH THREADER: {}".format(message))



import os
# Setup logging
LOG_FILENAME = "bot_files/logs/"
os.makedirs(os.path.dirname("bot_files/logs/"), exist_ok=True)
logging.basicConfig(format='%(asctime)s | %(levelname)s | %(message)s')
logging_levels = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]
loggers = []
for logger_level in logging_levels:
    name = logging.getLevelName(logger_level)
    logger = logging.getLogger(name + " logger")
    logger.setLevel(logger_level)
    handler = logging.handlers.RotatingFileHandler(LOG_FILENAME + name + ".LOG",
                                                   maxBytes=50000,
                                                   backupCount=5)
    logger.addHandler(handler)
    loggers.append(logger)



log_information("STARTUP",
                level=logging.INFO)

r,admin,username,password,subreddit,user_agent,id,secret,redirect = setup()
telegram_bot_token = sys.argv[9]
telegram_owner = sys.argv[10]
message_bot("Bot starting.")
readData()

if len(sys.argv) > 1:
    if sys.argv[1] == 'reset':
        resetAll()

running = True
sf_teams = {}
personal_teams = {}
sf_attempts = 30
personal_attempts = 30
while running:
    try:
        checkAndCreate()
        sf_attempts, sf_teams = check_spfl_games(sf_attempts, sf_teams)
        personal_attempts, personal_teams = check_sub_games(personal_attempts, personal_teams)
        updateThreads()
        log_information(getTimestamp() + "[SLEEPING FOR 60 SECONDS]",
                        level=logging.INFO)

        sleep(60)
    except KeyboardInterrupt:
        log_information("MANUAL SHUTDOWN",
                        level=logging.INFO)
        running = False
    except AssertionError:
        log_information("Assertion error, refreshing login",
                        level=logging.CRITICAL)
        r.clear_authentication()
        r.set_oauth_app_info(client_id=id,client_secret=secret,redirect_uri=redirect)
        OAuth_login()
    except praw.exceptions.APIException as e:
        log_information("API ERROR",
                        level=logging.CRITICAL)
        log_information("ERROR: {}".format(str(e)),
                        level=logging.CRITICAL)
        sleep(60)
    except praw.exceptions.ClientException as e:
        log_information("CLIENT ERROR",
                        level=logging.CRITICAL)
        log_information("ERROR: {}".format(str(e)),
                        level=logging.CRITICAL)
        sleep(60)
    except Exception as e:
        log_information("UNKNOWN ERROR: {}".format(str(e)),
                        level=logging.CRITICAL)
        sleep(60)
