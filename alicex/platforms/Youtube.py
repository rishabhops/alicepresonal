import asyncio
import os
import re
from typing import Union, Optional, Dict, List, Tuple
import logging
import json
from pathlib import Path

# Multiple library imports with fallbacks
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logging.warning("yt-dlp not available")

try:
    from pytube import YouTube, Search
    PYTUBE_AVAILABLE = True
except ImportError:
    PYTUBE_AVAILABLE = False
    logging.warning("pytube not available")

try:
    import youtube_dl
    YOUTUBE_DL_AVAILABLE = True
except ImportError:
    YOUTUBE_DL_AVAILABLE = False
    logging.warning("youtube-dl not available")

try:
    import requests
    from bs4 import BeautifulSoup
    WEB_SCRAPING_AVAILABLE = True
except ImportError:
    WEB_SCRAPING_AVAILABLE = False
    logging.warning("Web scraping dependencies not available")

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from alicex.utils.database import is_on_off
from alicex.utils.formatters import time_to_seconds

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def shell_cmd(cmd):
    """Enhanced shell command execution"""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, errorz = await proc.communicate()
        
        if errorz:
            error_msg = errorz.decode("utf-8")
            if "unavailable videos are hidden" in error_msg.lower():
                return out.decode("utf-8")
            else:
                return error_msg
        return out.decode("utf-8")
    except Exception as e:
        logger.error(f"Shell command failed: {str(e)}")
        return f"Error: {str(e)}"


class MultiLibraryYouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        
        # Ensure downloads directory exists
        self.downloads_dir = Path("downloads")
        self.downloads_dir.mkdir(exist_ok=True)
        
        # Library priority order (most reliable first)
        self.library_priority = []
        if PYTUBE_AVAILABLE:
            self.library_priority.append("pytube")
        if YTDLP_AVAILABLE:
            self.library_priority.append("yt-dlp")
        if YOUTUBE_DL_AVAILABLE:
            self.library_priority.append("youtube-dl")
        if WEB_SCRAPING_AVAILABLE:
            self.library_priority.append("web-scraping")
        
        logger.info(f"Available libraries: {self.library_priority}")

    def clean_url(self, link: str) -> str:
        """Clean YouTube URL"""
        if "&" in link:
            link = link.split("&")[0]
        if "?list=" in link:
            link = link.split("?list=")[0]
        return link.strip()

    def is_youtube_url(self, text: str) -> bool:
        """Check if text is a YouTube URL"""
        if not text:
            return False
        youtube_patterns = [
            r"(?:youtube\.com|youtu\.be)",
            r"youtube\.com/watch\?v=",
            r"youtu\.be/",
            r"youtube\.com/embed/",
            r"youtube\.com/v/",
        ]
        return any(re.search(pattern, text.strip()) for pattern in youtube_patterns)

    def safe_duration_format(self, duration) -> str:
        """Safely format duration"""
        try:
            if duration is None:
                return "0:00"
            
            if isinstance(duration, str):
                if duration in ["None", ""]:
                    return "0:00"
                if ":" in duration:
                    return duration
                try:
                    duration = float(duration)
                except:
                    return "0:00"
            
            if isinstance(duration, (int, float)):
                duration = int(duration)
                if duration <= 0:
                    return "0:00"
                
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                seconds = duration % 60
                
                if hours > 0:
                    return f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    return f"{minutes}:{seconds:02d}"
            
            return "0:00"
        except Exception:
            return "0:00"

    def extract_video_id(self, url: str) -> str:
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return ""

    async def search_with_pytube(self, query: str, limit: int = 1) -> Dict:
        """Search using pytube library"""
        try:
            if not PYTUBE_AVAILABLE:
                return {"result": []}
            
            loop = asyncio.get_running_loop()
            
            def pytube_search():
                try:
                    if self.is_youtube_url(query):
                        # Direct URL
                        yt = YouTube(query)
                        return [{
                            "title": yt.title,
                            "id": yt.video_id,
                            "duration": self.safe_duration_format(yt.length),
                            "thumbnails": [{"url": yt.thumbnail_url}],
                            "link": f"https://www.youtube.com/watch?v={yt.video_id}",
                            "channel": {"name": yt.author},
                            "viewCount": {"text": str(yt.views)}
                        }]
                    else:
                        # Search query
                        s = Search(query)
                        results = []
                        for video in s.results[:limit]:
                            results.append({
                                "title": video.title,
                                "id": video.video_id,
                                "duration": self.safe_duration_format(video.length),
                                "thumbnails": [{"url": video.thumbnail_url}],
                                "link": f"https://www.youtube.com/watch?v={video.video_id}",
                                "channel": {"name": video.author},
                                "viewCount": {"text": str(video.views)}
                            })
                        return results
                except Exception as e:
                    logger.error(f"Pytube search failed: {str(e)}")
                    return []
            
            results = await loop.run_in_executor(None, pytube_search)
            return {"result": results}
            
        except Exception as e:
            logger.error(f"Pytube search error: {str(e)}")
            return {"result": []}

    async def search_with_ytdlp(self, query: str, limit: int = 1) -> Dict:
        """Search using yt-dlp library"""
        try:
            if not YTDLP_AVAILABLE:
                return {"result": []}
            
            loop = asyncio.get_running_loop()
            
            def ytdlp_search():
                try:
                    if self.is_youtube_url(query):
                        search_query = query
                    else:
                        search_query = f"ytsearch{limit}:{query}"
                    
                    ytdl_opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "extract_flat": True,
                        "skip_download": True,
                    }
                    
                    with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                        search_info = ydl.extract_info(search_query, download=False)
                        
                        if not search_info:
                            return []
                        
                        results = []
                        entries = search_info.get("entries", [search_info]) if "entries" in search_info else [search_info]
                        
                        for entry in entries[:limit]:
                            if entry and entry.get("id"):
                                results.append({
                                    "title": entry.get("title", "Unknown"),
                                    "id": entry.get("id", ""),
                                    "duration": self.safe_duration_format(entry.get("duration")),
                                    "thumbnails": [{"url": entry.get("thumbnail", "")}],
                                    "link": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                                    "channel": {"name": entry.get("uploader", "Unknown")},
                                    "viewCount": {"text": str(entry.get("view_count", 0))}
                                })
                        return results
                except Exception as e:
                    logger.error(f"yt-dlp search failed: {str(e)}")
                    return []
            
            results = await loop.run_in_executor(None, ytdlp_search)
            return {"result": results}
            
        except Exception as e:
            logger.error(f"yt-dlp search error: {str(e)}")
            return {"result": []}

    async def search_with_youtube_dl(self, query: str, limit: int = 1) -> Dict:
        """Search using youtube-dl library"""
        try:
            if not YOUTUBE_DL_AVAILABLE:
                return {"result": []}
            
            loop = asyncio.get_running_loop()
            
            def youtubedl_search():
                try:
                    if self.is_youtube_url(query):
                        search_query = query
                    else:
                        search_query = f"ytsearch{limit}:{query}"
                    
                    ydl_opts = {
                        "quiet": True,
                        "extract_flat": True,
                    }
                    
                    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                        search_info = ydl.extract_info(search_query, download=False)
                        
                        results = []
                        entries = search_info.get("entries", [search_info]) if "entries" in search_info else [search_info]
                        
                        for entry in entries[:limit]:
                            if entry and entry.get("id"):
                                results.append({
                                    "title": entry.get("title", "Unknown"),
                                    "id": entry.get("id", ""),
                                    "duration": self.safe_duration_format(entry.get("duration")),
                                    "thumbnails": [{"url": entry.get("thumbnail", "")}],
                                    "link": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                                    "channel": {"name": entry.get("uploader", "Unknown")},
                                    "viewCount": {"text": str(entry.get("view_count", 0))}
                                })
                        return results
                except Exception as e:
                    logger.error(f"youtube-dl search failed: {str(e)}")
                    return []
            
            results = await loop.run_in_executor(None, youtubedl_search)
            return {"result": results}
            
        except Exception as e:
            logger.error(f"youtube-dl search error: {str(e)}")
            return {"result": []}

    async def search_with_web_scraping(self, query: str, limit: int = 1) -> Dict:
        """Fallback web scraping method"""
        try:
            if not WEB_SCRAPING_AVAILABLE:
                return {"result": []}
            
            # This is a basic implementation - you can enhance it
            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract video information from page
            # This is a simplified implementation
            results = []
            # Implementation would parse the YouTube search results page
            # For now, return empty to avoid complexity
            
            return {"result": results}
            
        except Exception as e:
            logger.error(f"Web scraping failed: {str(e)}")
            return {"result": []}

    async def multi_library_search(self, query: str, limit: int = 1) -> Dict:
        """Search using multiple libraries with fallback"""
        for library in self.library_priority:
            try:
                logger.info(f"Trying search with {library}")
                
                if library == "pytube":
                    result = await self.search_with_pytube(query, limit)
                elif library == "yt-dlp":
                    result = await self.search_with_ytdlp(query, limit)
                elif library == "youtube-dl":
                    result = await self.search_with_youtube_dl(query, limit)
                elif library == "web-scraping":
                    result = await self.search_with_web_scraping(query, limit)
                else:
                    continue
                
                if result and result.get("result"):
                    logger.info(f"Search successful with {library}")
                    return result
                else:
                    logger.warning(f"No results from {library}")
                    
            except Exception as e:
                logger.error(f"Search failed with {library}: {str(e)}")
                continue
        
        logger.error("All search methods failed")
        return {"result": []}

    # Keep all your existing method signatures for compatibility
    async def exists(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced URL validation"""
        try:
            if videoid:
                link = self.base + link
            return self.is_youtube_url(link)
        except Exception as e:
            logger.error(f"URL validation error: {str(e)}")
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        """Enhanced URL extraction"""
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        
        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        if text:
                            url = text[entity.offset : entity.offset + entity.length]
                            if await self.exists(url):
                                return url
                    elif entity.type == MessageEntityType.TEXT_LINK:
                        if await self.exists(entity.url):
                            return entity.url
            
            if message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        if await self.exists(entity.url):
                            return entity.url
                    elif entity.type == MessageEntityType.URL:
                        text = message.caption
                        if text:
                            url = text[entity.offset : entity.offset + entity.length]
                            if await self.exists(url):
                                return url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        """Get video details using multi-library approach"""
        try:
            if videoid:
                link = self.base + link
            
            search_result = await self.multi_library_search(link, 1)
            
            if not search_result.get("result"):
                return "Unknown", "0:00", 0, "", ""
            
            result = search_result["result"][0]
            
            title = result.get("title", "Unknown")
            duration_min = result.get("duration", "0:00")
            thumbnail = result.get("thumbnails", [{}])[0].get("url", "")
            if thumbnail and "?" in thumbnail:
                thumbnail = thumbnail.split("?")[0]
            vidid = result.get("id", "")
            
            try:
                if duration_min and duration_min != "0:00":
                    duration_sec = int(time_to_seconds(duration_min))
                else:
                    duration_sec = 0
            except:
                duration_sec = 0
                
            return title, duration_min, duration_sec, thumbnail, vidid
        except Exception as e:
            logger.error(f"Error getting video details: {str(e)}")
            return "Unknown", "0:00", 0, "", ""

    async def title(self, link: str, videoid: Union[bool, str] = None):
        """Get video title"""
        try:
            details = await self.details(link, videoid)
            return details[0] if details else "Unknown"
        except Exception as e:
            logger.error(f"Error getting title: {str(e)}")
            return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        """Get video duration"""
        try:
            details = await self.details(link, videoid)
            return details[1] if details else "0:00"
        except Exception as e:
            logger.error(f"Error getting duration: {str(e)}")
            return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        """Get video thumbnail"""
        try:
            details = await self.details(link, videoid)
            return details[3] if details else ""
        except Exception as e:
            logger.error(f"Error getting thumbnail: {str(e)}")
            return ""

    async def video(self, link: str, videoid: Union[bool, str] = None):
        """Get video stream URL using multiple libraries"""
        try:
            if videoid:
                link = self.base + link
            
            # Get proper URL if it's a search query
            if not self.is_youtube_url(link):
                search_result = await self.multi_library_search(link, 1)
                if search_result.get("result"):
                    link = search_result["result"][0].get("link", link)
                else:
                    return 0, "No search results found"
            
            # Try pytube first (often bypasses restrictions)
            if PYTUBE_AVAILABLE:
                try:
                    loop = asyncio.get_running_loop()
                    
                    def get_stream_url():
                        yt = YouTube(link)
                        stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
                        if stream:
                            return stream.url
                        # Fallback to adaptive streams
                        stream = yt.streams.get_highest_resolution()
                        return stream.url if stream else None
                    
                    stream_url = await loop.run_in_executor(None, get_stream_url)
                    if stream_url:
                        return 1, stream_url
                except Exception as e:
                    logger.warning(f"Pytube stream extraction failed: {str(e)}")
            
            # Fallback to other methods
            link = self.clean_url(link)
            
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-g",
                "-f", "best[height<=?720][width<=?1280]",
                "--no-warnings",
                "--quiet",
                "--socket-timeout", "30",
                link,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await proc.communicate()
            
            if stdout:
                return 1, stdout.decode().strip().split("\n")[0]
            else:
                error_msg = stderr.decode()
                logger.error(f"Video stream extraction failed: {error_msg}")
                return 0, error_msg
                
        except Exception as e:
            logger.error(f"Error getting video stream: {str(e)}")
            return 0, str(e)

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        """Get playlist using multiple methods"""
        try:
            if videoid:
                link = self.listbase + link
            link = self.clean_url(link)
            
            # Try pytube first
            if PYTUBE_AVAILABLE:
                try:
                    from pytube import Playlist
                    loop = asyncio.get_running_loop()
                    
                    def get_playlist():
                        p = Playlist(link)
                        return [url.split('v=')[1].split('&')[0] for url in p.video_urls[:limit]]
                    
                    result = await loop.run_in_executor(None, get_playlist)
                    if result:
                        return result
                except Exception as e:
                    logger.warning(f"Pytube playlist failed: {str(e)}")
            
            # Fallback to yt-dlp
            cmd = f"yt-dlp -i --get-id --flat-playlist --playlist-end {limit} --skip-download --no-warnings --quiet --socket-timeout 30 '{link}'"
            playlist = await shell_cmd(cmd)
            
            try:
                result = playlist.split("\n")
                result = [vid.strip() for vid in result if vid.strip() and len(vid.strip()) == 11]
            except Exception as e:
                logger.error(f"Playlist parsing error: {str(e)}")
                result = []
                
            return result
        except Exception as e:
            logger.error(f"Playlist extraction error: {str(e)}")
            return []

    async def track(self, link: str, videoid: Union[bool, str] = None):
        """Get track details with guaranteed structure"""
        default_track = {
            "title": "Unknown",
            "link": "",
            "vidid": "",
            "duration_min": "0:00",
            "thumb": "",
        }
        
        try:
            if videoid:
                link = self.base + link
            
            search_result = await self.multi_library_search(link, 1)
            
            if not search_result.get("result"):
                logger.warning(f"No search results found for track: {link}")
                return default_track, ""
            
            result = search_result["result"][0]
            
            track_details = {
                "title": result.get("title", "Unknown"),
                "link": result.get("link", ""),
                "vidid": result.get("id", ""),
                "duration_min": result.get("duration", "0:00"),
                "thumb": result.get("thumbnails", [{}])[0].get("url", "").split("?")[0] if result.get("thumbnails", [{}])[0].get("url") else "",
            }
            return track_details, result.get("id", "")
            
        except Exception as e:
            logger.error(f"Error getting track details: {str(e)}")
            return default_track, ""

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        """Get available formats"""
        try:
            if videoid:
                link = self.base + link
            
            if not self.is_youtube_url(link):
                search_result = await self.multi_library_search(link, 1)
                if search_result.get("result"):
                    link = search_result["result"][0].get("link", link)
            
            link = self.clean_url(link)
            
            # Try pytube first
            if PYTUBE_AVAILABLE:
                try:
                    loop = asyncio.get_running_loop()
                    
                    def get_formats():
                        yt = YouTube(link)
                        formats = []
                        for stream in yt.streams:
                            formats.append({
                                "format": f"{stream.mime_type} {stream.resolution or stream.abr}",
                                "filesize": stream.filesize or "Unknown",
                                "format_id": stream.itag,
                                "ext": stream.mime_type.split('/')[1] if stream.mime_type else "unknown",
                                "format_note": stream.resolution or stream.abr or "",
                                "resolution": stream.resolution or "audio only",
                                "yturl": link,
                            })
                        return formats
                    
                    formats_available = await loop.run_in_executor(None, get_formats)
                    return formats_available, link
                except Exception as e:
                    logger.warning(f"Pytube formats failed: {str(e)}")
            
            # Fallback to yt-dlp
            if YTDLP_AVAILABLE:
                ytdl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                }
                
                ydl = yt_dlp.YoutubeDL(ytdl_opts)
                
                with ydl:
                    formats_available = []
                    try:
                        r = ydl.extract_info(link, download=False)
                        
                        for format in r.get("formats", []):
                            try:
                                format_str = str(format.get("format", ""))
                            except:
                                continue
                                
                            if not "dash" in format_str.lower():
                                try:
                                    if all(key in format for key in ["format", "format_id", "ext"]):
                                        formats_available.append({
                                            "format": format.get("format"),
                                            "filesize": format.get("filesize", "Unknown"),
                                            "format_id": format.get("format_id"),
                                            "ext": format.get("ext"),
                                            "format_note": format.get("format_note", ""),
                                            "resolution": format.get("resolution", "Unknown"),
                                            "yturl": link,
                                        })
                                except:
                                    continue
                                    
                    except Exception as e:
                        logger.error(f"Format extraction failed: {str(e)}")
                        return [], link
                        
                return formats_available, link
            
            return [], link
        except Exception as e:
            logger.error(f"Error getting formats: {str(e)}")
            return [], link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        """Get similar videos"""
        try:
            if videoid:
                link = self.base + link
            
            search_result = await self.multi_library_search(link, 10)
            result = search_result.get("result", [])
            
            if query_type < len(result):
                video = result[query_type]
                return (
                    video.get("title", "Unknown"),
                    video.get("duration", "0:00"),
                    video.get("thumbnails", [{}])[0].get("url", "").split("?")[0],
                    video.get("id", "")
                )
            else:
                return "Unknown", "0:00", "", ""
        except Exception as e:
            logger.error(f"Error in slider: {str(e)}")
            return "Unknown", "0:00", "", ""

    def safe_filename(self, filename: str) -> str:
        """Create safe filename"""
        if not filename:
            return "unknown"
        
        safe_name = re.sub(r'[<>:"/\\|?*]', '', filename)
        safe_name = re.sub(r'[\s\-]+', '_', safe_name)
        safe_name = safe_name[:100] if len(safe_name) > 100 else safe_name
        safe_name = safe_name if safe_name else "unknown"
        
        return safe_name

    async def download(
        self,
        link: str,
        mystic=None,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ):
        """Enhanced download with multiple library support"""
        try:
            if videoid:
                link = self.base + link
            
            # Get proper URL and title
            if not self.is_youtube_url(link):
                search_result = await self.multi_library_search(link, 1)
                if search_result.get("result"):
                    video_info = search_result["result"][0]
                    link = video_info.get("link", link)
                    if not title:
                        title = self.safe_filename(video_info.get("title", "unknown"))
                else:
                    logger.error("No search results found for download")
                    return None
            
            link = self.clean_url(link)
            loop = asyncio.get_running_loop()

            # Try pytube first (often works without authentication)
            if PYTUBE_AVAILABLE and not songaudio and not songvideo:
                try:
                    def pytube_download():
                        yt = YouTube(link)
                        
                        if video:
                            stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
                            if not stream:
                                stream = yt.streams.get_highest_resolution()
                        else:
                            stream = yt.streams.filter(only_audio=True).first()
                        
                        if stream:
                            filename = stream.download(output_path=str(self.downloads_dir))
                            return filename
                        return None
                    
                    downloaded_file = await loop.run_in_executor(None, pytube_download)
                    if downloaded_file:
                        return downloaded_file, True
                except Exception as e:
                    logger.warning(f"Pytube download failed: {str(e)}")

            # Fallback to yt-dlp methods
            def audio_dl():
                ydl_optssx = {
                    "quiet": True,
                    "no_warnings": True,
                    "format": "bestaudio/best",
                    "outtmpl": str(self.downloads_dir / "%(id)s.%(ext)s"),
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, False)
                
                if not info:
                    raise Exception("Failed to extract video info")
                
                video_id = info.get('id', 'unknown')
                file_ext = info.get('ext', 'webm')
                
                for ext in [file_ext, 'webm', 'mp4', 'm4a', 'opus']:
                    potential_file = self.downloads_dir / f"{video_id}.{ext}"
                    if potential_file.exists():
                        return str(potential_file)
                
                x.download([link])
                
                for ext in ['webm', 'mp4', 'm4a', 'opus']:
                    potential_file = self.downloads_dir / f"{video_id}.{ext}"
                    if potential_file.exists():
                        return str(potential_file)
                
                return str(self.downloads_dir / f"{video_id}.{file_ext}")

            def video_dl():
                ydl_optssx = {
                    "quiet": True,
                    "no_warnings": True,
                    "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])/best[height<=?720]",
                    "outtmpl": str(self.downloads_dir / "%(id)s.%(ext)s"),
                    "merge_output_format": "mp4",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, False)
                
                if not info:
                    raise Exception("Failed to extract video info")
                
                video_id = info.get('id', 'unknown')
                potential_file = self.downloads_dir / f"{video_id}.mp4"
                
                if potential_file.exists():
                    return str(potential_file)
                
                x.download([link])
                return str(potential_file)

            def song_video_dl():
                safe_title = self.safe_filename(str(title)) if title else "unknown"
                formats = f"{format_id}+140" if format_id else "best"
                fpath = str(self.downloads_dir / f"{safe_title}.%(ext)s")
                
                ydl_optssx = {
                    "quiet": True,
                    "no_warnings": True,
                    "format": formats,
                    "outtmpl": fpath,
                    "prefer_ffmpeg": True,
                    "merge_output_format": "mp4",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                x.download([link])
                
                return str(self.downloads_dir / f"{safe_title}.mp4")

            def song_audio_dl():
                safe_title = self.safe_filename(str(title)) if title else "unknown"
                fpath = str(self.downloads_dir / f"{safe_title}.%(ext)s")
                
                ydl_optssx = {
                    "quiet": True,
                    "no_warnings": True,
                    "format": format_id if format_id else "bestaudio/best",
                    "outtmpl": fpath,
                    "prefer_ffmpeg": True,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                x.download([link])
                
                return str(self.downloads_dir / f"{safe_title}.mp3")

            if songvideo:
                downloaded_file = await loop.run_in_executor(None, song_video_dl)
                return downloaded_file
            elif songaudio:
                downloaded_file = await loop.run_in_executor(None, song_audio_dl)
                return downloaded_file
            elif video:
                if await is_on_off(1):
                    direct = True
                    downloaded_file = await loop.run_in_executor(None, video_dl)
                else:
                    proc = await asyncio.create_subprocess_exec(
                        "yt-dlp",
                        "-g",
                        "-f", "best[height<=?720][width<=?1280]",
                        "--no-warnings",
                        "--quiet",
                        "--socket-timeout", "30",
                        link,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if stdout:
                        downloaded_file = stdout.decode().strip().split("\n")[0]
                        direct = None
                    else:
                        return None
            else:
                direct = True
                downloaded_file = await loop.run_in_executor(None, audio_dl)
            
            # Verify file exists
            if isinstance(downloaded_file, str) and not downloaded_file.startswith("http"):
                if not os.path.exists(downloaded_file):
                    logger.error(f"Downloaded file does not exist: {downloaded_file}")
                    return None
            
            return downloaded_file, direct if 'direct' in locals() else True
            
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            return None


# For backward compatibility, use the original class name
class YouTubeAPI(MultiLibraryYouTubeAPI):
    pass
