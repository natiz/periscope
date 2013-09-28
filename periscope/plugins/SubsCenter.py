# -*- coding: utf-8 -*-

#   This file was developed for periscope
#   By Nati Ziv
#   
#   Periscope
#   Copyright (c) 2008-2011 Patrick Dessalle <patrick@dessalle.be>
#
#    periscope is free software; you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    periscope is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with periscope; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import zipfile, os, urllib2, urllib, logging, traceback, httplib, re, json
from BeautifulSoup import BeautifulSoup

import SubtitleDatabase

log = logging.getLogger(__name__)

LANGUAGES = {u"Hebrew" : "he",
                         u"English" : "en"}

class SubsCenter(SubtitleDatabase.SubtitleDB):
    url = "http://www.subscenter.org"
    site_name = "SubsCenter.org"
    
    URL_SEARCH_PATTERN = "%s/he/subtitle/search/?q=%s"
    URL_SHOW_PATTERN = "%s%s%s/%s"
    URL_MOVIE_PATTERN = "%s%s"
    URL_DOWNLOAD_PATTERN = "%s/he/subtitle/download/he/%s/?v=%s&key=%s"

    def __init__(self, config, cache_folder_path):
        super(SubsCenter, self).__init__(langs=None,revertlangs=LANGUAGES)
        self.host = "http://www.subscenter.org"       

    def process(self, filepath, langs):
        ''' main method to call on the plugin, pass the filename and the wished 
        languages and it will query the subtitles source '''
        fname = unicode(self.getFileName(filepath).lower())
        guessedData = self.guessFileData(fname)
        if guessedData['type'] == 'tvshow':
            subs = self.query(fname, guessedData, langs)
            return subs
        elif guessedData['type'] == 'movie':
             subs = self.query(fname, guessedData, langs)
             return subs
        else:
            return []
    
    def query(self, fname, meta, langs):
        ''' makes a query and returns info (link, lang) about found subtitles'''
        sublinks = []
        name = re.sub(r'\s+', ' ', meta['name'].replace('and','').replace('.',' ')).lower().strip().replace(" ", "+")
        searchurl = self.URL_SEARCH_PATTERN %(self.host, name)
        log.debug("Search URL: %s", searchurl)
        try:
            res = urllib2.urlopen(searchurl)
            content = res.read()
            resurl = res.geturl()
        except urllib2.HTTPError as inst:
            logging.debug("Error : %s for %s" % (searchurl, inst))
            return sublinks
        
        if not content: # no results
            return sublinks
        elif resurl != searchurl: # one result, redirect
            matchurl = resurl
        else: # multiple search results
            soup = BeautifulSoup(content)
            matches = []
            for match in soup("div", {"class": "generalWindowRight"}):
                if not match.a: return sublinks
                if meta['type'].replace("tvshow", "series") in match.a.get('href'):
                    log.debug("Match: %s", match.a.get('href'))
                    matches.append(match.a.get('href'))
            if len(matches) == 0 or len(matches) > 8: # too many, or non
                return sublinks
            elif len(matches) == 1: # only one rsult
                matchurl = matches[0]
            else: # multiple results, match with iMDB
                fimdbid = self.getImdb(meta['name'], meta['type'])
                for match in matches:
                    content = self.downloadContent("%s%s" %(self.host, match), 10)
                    if not content: continue
                    soup = BeautifulSoup(content)
                    simdbid = soup('a', href=re.compile('imdb'))[0].get('href')
                    if fimdbid in simdbid:
                        log.debug("Match for %s: %s (imdb) %s (subs)" %(meta['name'], fimdbid, simdbid))
                        matchurl = match
                        break
                    else:
                        log.debug("No match for %s: %s (imdb) %s (subs)" %(meta['name'], fimdbid, simdbid))
        
        if not matchurl: return sublinks
        if meta['type'] == 'tvshow':
            suburl = self.URL_SHOW_PATTERN %(self.host, matchurl, meta['season'], meta['episode'])
        else:
            suburl = self.URL_MOVIE_PATTERN %(self.host, matchurl)
        
        log.debug("Sub URL: %s", suburl)
        content = self.downloadContent(suburl, 10)
        if not content: return sublinks
        subs_json = re.compile('subtitles_groups = ({.*?})\s', re.DOTALL)
        subs_data = subs_json.search(content)
        try:
            subs = json.loads(subs_data.group(1))
        except:
            log.debug("subtitles_groups parsing error")
            return sublinks
        for lkey, lang in subs.items():
            if langs and not lkey in langs:
                continue
            for skey,subbers in lang.items():
                for qkey,quality in subbers.items():
                    for qsub,sub in quality.items():
                        releaseMeta = self.guessFileData(sub['subtitle_version'])
                        teams = set([t.replace('[','').replace(']','') for t in meta['teams']])
                        subTeams = set(releaseMeta['teams'])
                        result = {}
                        result["release"] = sub["subtitle_version"]
                        result["lang"] = lkey
                        result["link"] = self.URL_DOWNLOAD_PATTERN %(self.host, sub['id'], sub['subtitle_version'], sub['key'])
                        result["page"] = searchurl
                        if result['release'].startswith(fname) or (releaseMeta['name'].replace('.',' ').replace(':','').replace('-','').strip() == meta['name'].replace('.',' ').replace(':','').replace('-','').strip() and (teams.issubset(subTeams) or subTeams.issubset(teams))):
                            sublinks.append(result)
                
        return sublinks
    def getImdb (self, title, type):
        '''Get iMDB ID'''
        searchurl = "http://mymovieapi.com/?q=%s&mt=%s&episode=0" %(title, type.replace("tvshow","TVS").replace("movie","M"))
        content = self.downloadContent(searchurl, 10)
        if not content: return ""
        try:
            data = eval(content)
        except:
            log.debug("iMDB parsing error for URL: %s", searchurl)
            return ""
        return data[0]['imdb_id']
        
    def createFile(self, subtitle):
        '''pass the URL of the sub and the file it matches, will unzip it
        and return the path to the created file'''
        suburl = subtitle["link"]
        videofilename = subtitle["filename"]
        srtbasefilename = videofilename.rsplit(".", 1)[0]
        srtfilename = srtbasefilename +".srt"
        self.downloadFile(suburl, srtfilename)
        return srtfilename

    def downloadFile(self, url, filename):
        ''' Downloads the given url to the given filename '''
        req = urllib2.Request(url, headers={'Referer' : url, 'User-Agent' : 'Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.1.3)'})
        
        f = urllib2.urlopen(req)
        dump = open(filename, "wb")
        dump.write(f.read())
        dump.close()
        f.close()
