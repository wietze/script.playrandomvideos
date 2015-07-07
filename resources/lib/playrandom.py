from __future__ import unicode_literals

import json
import urllib
import xbmc
import xbmcvfs

import xml.etree.ElementTree as ET
from random import shuffle

from devhelper import pykodi
from devhelper.pykodi import log
from devhelper.pykodi import wait
from episode import Episode
from movie import Movie
from video import Video

def library_path(path):
    db_path = path.split('://')[1].split('?', 1)
    query = urllib.unquote(db_path[1]) if len(db_path) > 1 else None
    db_path = db_path[0].rstrip('/').split('/')

    return {'db_path': db_path, 'query': query}

def play_videos(playable_items):
    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
    playlist.clear()
    for playable_item in playable_items:
        playlist.add(playable_item.file.encode('utf-8'), playable_item.listitem)

    xbmc.Player().play(playlist)


class RandomPlayer(object):
    def __init__(self):
        self.playlist_limit_length = 5
        self.video_database_prefix = 'videodb://'
        self.music_database_prefix = 'musicdb://'
        self.playlist_suffix = '.xsp'
        self.tvshow_library = 'tvshows'
        self.movie_library = 'movies'

    # I would also like to support a list of items directly, for instance if several movies are selected, a method
    #  would accept a list of the full paths to the movies, and then play those randomly. Probably even a list of
    #  container paths, that would then need to be resolved and fetched, much like tvshow/genres/<genreid>
    def play_random_from_full_url(self, path, media='video'):
        if path.startswith(self.video_database_prefix):
            self._play_random_from_video_db(path)
        elif path.startswith(self.music_database_prefix):
            self._play_random_from_music_db(path)
        elif path.endswith(self.playlist_suffix):
            self._play_random_from_playlist(path)
        elif path.startswith('plugin://'):
            log("Unsupported path, but I think it's a plugin path '%s'" % path, xbmc.LOGNOTICE)
        elif path.startswith('library://'):
            log("Unsupported path, but I think it's a top level library .xml file '%s'" % path, xbmc.LOGNOTICE)
        else: # others in 'special://', as well as 'file://', 'smb://', 'nfs://', and other file systems
            self._play_random_from_file_system(path, media)

    def _play_random_from_video_db(self, path):
        _path = library_path(path)['db_path']
        if not _path:
            log("Unsupported Video DB path '%s'. Investigate if there is a query." % path, xbmc.LOGNOTICE)
        library = _path[0]
        _path = None

        if library == self.tvshow_library:
            self._play_random_tv_episodes_by_path(path)
        elif library == self.movie_library:
            self._play_random_movies_by_path(path)
        else:
            log("Unsupported Video DB path '%s'." % path, xbmc.LOGNOTICE)


    def _play_random_tv_episodes_by_path(self, path):
        db_path = library_path(path)['db_path']
        path_len = len(db_path)

        category = db_path[1] if path_len > 1 else None
        if category == 'titles':
            tvshow_id = db_path[2] if path_len > 2 else None
            season = db_path[3] if path_len > 3 else None
            # Will play from the season if an episode was passed in
            self._play_random_tv_episodes(tvshow_id, season)
        else: # genres/years/actors/studios/tags
            if path_len < 3: # No category_id
                self._play_random_tv_episodes()
            elif path_len == 3:
                categoryId = db_path[2]
                self._play_random_tv_episodes_from_category(category, categoryId)
            else:
                # With a TV show selected we just ignore the initial filter, it was only meant to filter the TV show selection
                tvshow_id = db_path[3] if path_len > 2 else None
                season = db_path[4] if path_len > 3 else None
                self._play_random_tv_episodes(tvshow_id, season)


    def _play_random_tv_episodes(self, tvshow_id=None, season=None):
        random_episodes = self._get_random_tv_episodes(tvshow_id, season)
        _method_args = "(tvshow_id=%s, season=%s)" % (str(tvshow_id), str(season))
        if random_episodes:
            play_videos(random_episodes)
            log("Successfully started playing random episodes with %s" % _method_args, xbmc.LOGDEBUG)
        else:
            log("Didn't find any episodes with %s" % _method_args, xbmc.LOGNOTICE)


    def _play_random_tv_episodes_from_category(self, category, category_id):
        category_lookup = {
            'genres': 'genreid',
            'years': 'year',
            'actors': 'actor', # TODO: The Actor filter expects an actor string, probably name. Frig
            'studios': 'studio', # Also not working
            'tags': 'tag'}
        category = category_lookup[category]

        if category == 'genreid' or category == 'year':
            category_id = int(category_id)

        json_request = {'jsonrpc': '2.0', 'method': 'VideoLibrary.GetTVShows', 'id': 1,
            'params': {'filter':{category: category_id}}}

        json_tvshows = pykodi.execute_jsonrpc(json_request)

        _method_args = "(%s=%s)" % (str(category), str(category_id))
        if 'result' not in json_tvshows:
            log("JSON-RPC query '%s'; result '%s'" % (json.dumps(json_request, ensure_ascii=False), json.dumps(json_tvshows, ensure_ascii=False)), xbmc.LOGWARNING)
        if 'tvshows' in json_tvshows['result']:
            random_episodes = []
            for show in json_tvshows['result']['tvshows']:
                random_episodes.extend(self._get_random_tv_episodes(show['tvshowid']))
            shuffle(random_episodes)
            random_episodes = random_episodes[:self.playlist_limit_length]
            play_videos(random_episodes)
            log("Successfully started playing random episodes with %s" % _method_args)
        else:
            log("Didn't find any tv shows with %s" % _method_args)


    def _get_random_tv_episodes(self, tvshow_id=None, season=None):
        json_request = {'jsonrpc': '2.0', 'method': 'VideoLibrary.GetEpisodes', 'id': 1,
            'params': {'properties': ['file', 'title', 'season', 'episode', 'showtitle'], 'sort': {'method': 'random'}, 'limits': {'end': self.playlist_limit_length}}}

        if tvshow_id:
            json_request['params']['tvshowid'] = int(tvshow_id)
            if season and not season == '-1': # even though this param defaults to -1 for all seasons, it still chokes if passed in
                json_request['params']['season'] = int(season)

        json_episodes = pykodi.execute_jsonrpc(json_request)

        if 'result' in json_episodes:
            return [Episode(episode) for episode in json_episodes['result']['episodes']]
        else:
            return []


    def _play_random_movies_by_path(self, path):
        # For movies I don't have to deal with many paths that can't be listed directly, so 'Files.GetDirectory' is the most straightforward option
        original_path = path
        db_path = library_path(path)['db_path']
        path_len = len(db_path)

        category = db_path[1] if path_len > 1 else None

        # Just pick from all movies if there is no movie ID or category ID
        if path_len < 3:
            path = 'videodb://movies/titles/'

        # This will fail if a movie is passed in directly, 'movies/titles/<movieid>' or 'movies/<category>/<categoryid>/<movieid>'
        json_movies = self._get_all_media_from_directory(path, 'video', ['title'], shuffle_list=True, limit=True)
        if json_movies:
            random_movies = [Movie(movie) for movie in json_movies]
            play_videos(random_movies)
            log("Successfully started playing random movies from '%s'" % original_path, xbmc.LOGDEBUG)
        else:
            log("Didn't find any movies from '%s'" % original_path, xbmc.LOGNOTICE)


    # From context.playrandom, which passes along ListItem.FolderPath from the context menu, db_path and query can be goofy
    # a simple 'db_path' like 'tvshows/titles/<tvshowid>[/<season>[/episodeid]]' is clear enough
    # - also the head of sub-sections are fine; 'tvshows/genres/<genreid>'
    # - but going deeper 'tvshows/genres/<genreid>/<tvshowid>/<season>/<episodeid>' gets a bit murky
    # - But! to turn this guy back in to what is clear, just replace 'genres/<genreid>' with 'titles'
    #  - We only really expect the genre to apply to the TV show selection, then list all seasons and episodes contained within
    #  - Ditto years/actors/studios/tags
    # 'query' is very icky. It looks acceptable, but it does not always accurately describe either the ListItem or its Container.
    # - Most of the time, it is simply in the reverse order of the path used to get to the Container of the ListItem, rather than the ListItem itself
    #  - The query for 'tvshows/year/<year>/<tvshowid>/<season>/<episodeid>' is 'season=<season>&tvshowid=<tvshowid>&year=<year>'
    #  - even when the selected season/episode ListItem aired in a different year, the <year> selected when navigating is displayed
    #  - even when the Container aired in a different year (or doesn't have an associated year), the year is displayed, with the wrong value
    # - Rarely it does actually describe the ListItem itself
    #  - ListItem 'movies/sets/<setid>' is the one culprit, and has a query of 'setid=<setid>'
    # - Sometimes it also includes an 'xsp' query, which is JSON that describes more of the Container's info, such as sort, filter
    #  - This seems to happen when navigating from the virtual library directory tree, rather than when accessed with a 'videodb://tvshows/titles/' URL.
    #  - A ListItem inside of a smart playlist it fully describes the rules the smart playlist is built with
    #  - In Progress TV Shows path is a nice 'tvshows/titles/<tvshowid>' and the xsp is a filter for inprogress
    # path = 'tvshows/year/<year>/<tvshowid>/<season>/<episodeid>' query = 'season=<season>&tvshowid=<tvshowid>&year=<year>' : ICK
    # KODI--: This is just... an important API with an unpleasant design
    # KODI-ODD: sometimes db_path has a slash at the end and sometimes it does not

    def _play_random_from_music_db(self, path):
        log("Don't know how to play from the music library yet '{}'".format(path))

    def _play_random_from_playlist(self, path):
        playlist_xml = xbmcvfs.File(path.encode('utf-8'), 'r')
        playlist_xml = playlist_xml.read()
        playlist_xml = ET.fromstring(playlist_xml)

        if playlist_xml.tag != 'smartplaylist':
            log("Playlists other than smart playlists are not supported. '%s'" % path, xbmc.LOGNOTICE)
            return
        if 'type' not in playlist_xml.attrib:
            log("Playlists without a type are not supported. '%s'" % path, xbmc.LOGNOTICE)
            return

        playlist_type = playlist_xml.attrib['type']
        if playlist_type == 'episodes':
            self._play_random_from_episode_playlist(path)
        elif playlist_type == 'movies':
            self._play_random_from_movie_playlist(path)
        else:
            log("Unsupported playlist type '%s' for path '%s'" % (playlist_type, path), xbmc.LOGNOTICE)


    def _play_random_from_episode_playlist(self, path):
        json_episodes = self._get_all_media_from_directory(path, 'video', ['title', 'season', 'episode', 'showtitle'], shuffle_list=True, limit=True)
        if json_episodes:
            random_episodes = [Episode(episode) for episode in json_episodes]
            play_videos(random_episodes)
            log("Successfully started playing random episodes from '%s'" % path, xbmc.LOGDEBUG)
        else:
            log("Didn't find any episodes from '%s'" % path, xbmc.LOGNOTICE)


    def _play_random_from_movie_playlist(self, path):
        json_movies = self._get_all_media_from_directory(path, 'video', ['title'], shuffle_list=True, limit=True)
        if json_movies:
            random_movies = [Movie(movie) for movie in json_movies]
            play_videos(random_movies)
            log("Successfully started playing random movies from '%s'" % path, xbmc.LOGDEBUG)
        else:
            log("Didn't find any movies from '%s'" % path, xbmc.LOGNOTICE)


    def _play_random_from_file_system(self, path, media='video'):
        json_media = self._get_all_media_from_directory(path, media, recursive=True, shuffle_list=True, limit=True)
        if json_media:
            if media == 'video':
                videos = [Video(video) for video in json_media]
                play_videos(videos)
                log("Successfully started playing random '%s' from '%s'" % (media, path), xbmc.LOGDEBUG)
            else:
                log("Unsupported path for '%s', but it's a file system path '%s'" % (media, path), xbmc.LOGNOTICE)
        else:
            log("Didn't find any playable '%s' from '%s'" % (media, path), xbmc.LOGNOTICE)


    def _get_all_media_from_directory(self, path, media='video', properties=None, recursive=False, shuffle_list=False, limit=False):
        # 'type' and 'id' pop out of this when the files are in the library; for instance 'type': 'episode', 'id': 79254
        # directories are 'filetype': 'directory'
        # 'video', 'music', 'pictures', 'files', 'programs'
        json_request = {'jsonrpc': '2.0', 'method': 'Files.GetDirectory', 'id': 1,
            'params': {'directory': path, 'media': media}}
        if properties:
            json_request['params']['properties'] = properties
        json_result = pykodi.execute_jsonrpc(json_request)
        if 'result' in json_result and 'files' in json_result['result']:
            json_files = json_result['result']['files']
            if recursive:
                result = []
                for file in json_files:
                    if file['filetype'] == 'directory':
                        result.extend(self._get_all_media_from_directory(file['file'], media, properties, recursive))
                    else:
                        result.append(file)
                if shuffle_list:
                    shuffle(result)
                if limit:
                    result = result[:self.playlist_limit_length]
                return result
            else:
                if shuffle_list:
                    shuffle(json_files)
                if limit:
                    json_files = json_files[:self.playlist_limit_length]
                return json_files
        else:
            return []
