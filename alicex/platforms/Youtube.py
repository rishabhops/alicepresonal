import asyncio
import os
import re
from typing import Union, Optional, Dict, List, Tuple
import logging
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from alicex.utils.database import is_on_off
from alicex.utils.formatters import time_to_seconds

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def shell_cmd(cmd):
    """Enhanced shell command execution with better error handling"""
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
            elif "video unavailable" in error_msg.lower():
                logger.warning(f"Video unavailable: {error_msg}")
                return ""
            else:
                return error_msg
        return out.decode("utf-8")
    except Exception as e:
        logger.error(f"Shell command failed: {str(e)}")
        return f"Error: {str(e)}"


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        
        # Enhanced yt-dlp base options without cookies
        self.base_ytdl_opts = {
            "geo_bypass": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "ignoreerrors": True,
            "no_color": True,
        }

    def clean_url(self, link: str) -> str:
        """Clean YouTube URL by removing unnecessary parameters"""
        if "&" in link:
            link = link.split("&")[0]
        if "?list=" in link:
            link = link.split("?list=")[0]
        return link

    def is_youtube_url(self, text: str) -> bool:
        """Check if text is a YouTube URL"""
        youtube_patterns = [
            r"(?:youtube\.com|youtu\.be)",
            r"youtube\.com/watch\?v=",
            r"youtu\.be/",
            r"youtube\.com/embed/",
            r"youtube\.com/v/",
        ]
        return any(re.search(pattern, text) for pattern in youtube_patterns)

    async def search_youtube_with_ytdlp(self, query: str, limit: int = 1):
        """Search YouTube using yt-dlp instead of youtubesearchpython"""
        try:
            # If it's already a URL, use it directly
            if self.is_youtube_url(query):
                search_query = query
            else:
                # Use yt-dlp search functionality
                search_query = f"ytsearch{limit}:{query}"
            
            loop = asyncio.get_running_loop()
            
            def extract_search_info():
                ytdl_opts = {
                    **self.base_ytdl_opts,
                    "skip_download": True,
                    "extract_flat": True if not self.is_youtube_url(query) else False,
                }
                
                with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                    info = ydl.extract_info(search_query, download=False)
                    return info
            
            info = await loop.run_in_executor(None, extract_search_info)
            
            if not info:
                return {"result": []}
            
            # Handle search results vs direct URL
            if "entries" in info and info["entries"]:
                # Search results
                results = []
                for entry in info["entries"][:limit]:
                    if not entry:
                        continue
                    
                    duration = entry.get("duration", 0)
                    duration_str = f"{duration//60}:{duration%60:02d}" if duration else "0:00"
                    
                    results.append({
                        "title": entry.get("title", "Unknown"),
                        "id": entry.get("id", ""),
                        "duration": duration_str,
                        "thumbnails": [{"url": entry.get("thumbnail", "")}] if entry.get("thumbnail") else [{"url": ""}],
                        "link": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        "channel": {"name": entry.get("uploader", "Unknown")},
                        "viewCount": {"text": str(entry.get("view_count", 0))}
                    })
                return {"result": results}
            else:
                # Direct URL result
                duration = info.get("duration", 0)
                duration_str = f"{duration//60}:{duration%60:02d}" if duration else "0:00"
                
                return {
                    "result": [{
                        "title": info.get("title", "Unknown"),
                        "id": info.get("id", ""),
                        "duration": duration_str,
                        "thumbnails": [{"url": info.get("thumbnail", "")}],
                        "link": query if self.is_youtube_url(query) else f"https://www.youtube.com/watch?v={info.get('id', '')}",
                        "channel": {"name": info.get("uploader", "Unknown")},
                        "viewCount": {"text": str(info.get("view_count", 0))}
                    }]
                }
                
        except Exception as e:
            logger.error(f"YouTube search with yt-dlp failed: {str(e)}")
            return {"result": []}

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
        """Enhanced URL extraction with better error handling"""
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        
        for message in messages:
            # Check text entities
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
            
            # Check caption entities
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
        """Enhanced video details using yt-dlp only"""
        try:
            if videoid:
                link = self.base + link
            link = self.clean_url(link)
            
            search_result = await self.search_youtube_with_ytdlp(link, 1)
            
            if not search_result.get("result"):
                return "Unknown", "0:00", 0, "", ""
            
            result = search_result["result"][0]
            
            title = result.get("title", "Unknown")
            duration_min = result.get("duration", "0:00")
            thumbnail = result.get("thumbnails", [{}])[0].get("url", "").split("?")[0]
            vidid = result.get("id", "")
            
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
                
            return title, duration_min, duration_sec, thumbnail, vidid
        except Exception as e:
            logger.error(f"Error getting video details: {str(e)}")
            return "Unknown", "0:00", 0, "", ""

    async def title(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced title extraction"""
        try:
            if videoid:
                link = self.base + link
            link = self.clean_url(link)
            
            search_result = await self.search_youtube_with_ytdlp(link, 1)
            
            if search_result.get("result"):
                return search_result["result"][0].get("title", "Unknown")
            return "Unknown"
        except Exception as e:
            logger.error(f"Error getting title: {str(e)}")
            return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced duration extraction"""
        try:
            if videoid:
                link = self.base + link
            link = self.clean_url(link)
            
            search_result = await self.search_youtube_with_ytdlp(link, 1)
            
            if search_result.get("result"):
                return search_result["result"][0].get("duration", "0:00")
            return "0:00"
        except Exception as e:
            logger.error(f"Error getting duration: {str(e)}")
            return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced thumbnail extraction"""
        try:
            if videoid:
                link = self.base + link
            link = self.clean_url(link)
            
            search_result = await self.search_youtube_with_ytdlp(link, 1)
            
            if search_result.get("result"):
                return search_result["result"][0].get("thumbnails", [{}])[0].get("url", "").split("?")[0]
            return ""
        except Exception as e:
            logger.error(f"Error getting thumbnail: {str(e)}")
            return ""

    async def video(self, link: str, videoid: Union[bool, str] = None):
        """Cookie-free video stream URL extraction with search support"""
        try:
            if videoid:
                link = self.base + link
            
            # If it's not a URL, search for it first
            if not self.is_youtube_url(link):
                search_result = await self.search_youtube_with_ytdlp(link, 1)
                if search_result.get("result"):
                    link = search_result["result"][0].get("link", link)
            
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
        """Enhanced playlist extraction without cookies"""
        try:
            if videoid:
                link = self.listbase + link
            link = self.clean_url(link)
            
            cmd = f"yt-dlp -i --get-id --flat-playlist --playlist-end {limit} --skip-download --no-warnings --quiet --socket-timeout 30 '{link}'"
            playlist = await shell_cmd(cmd)
            
            try:
                result = playlist.split("\n")
                # Filter out empty strings and invalid video IDs
                result = [vid.strip() for vid in result if vid.strip() and len(vid.strip()) == 11]
            except Exception as e:
                logger.error(f"Playlist parsing error: {str(e)}")
                result = []
                
            return result
        except Exception as e:
            logger.error(f"Playlist extraction error: {str(e)}")
            return []

    async def track(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced track details with guaranteed return structure and search support"""
        # Default structure to prevent KeyError
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
            
            # Use yt-dlp search for everything now
            search_result = await self.search_youtube_with_ytdlp(link, 1)
            
            if not search_result.get("result"):
                logger.warning(f"No search results found for: {link}")
                return default_track, ""
            
            result = search_result["result"][0]
            
            title = result.get("title", "Unknown")
            duration_min = result.get("duration", "0:00")
            vidid = result.get("id", "")
            yturl = result.get("link", "")
            thumbnail = result.get("thumbnails", [{}])[0].get("url", "").split("?")[0]
            
            track_details = {
                "title": title,
                "link": yturl,
                "vidid": vidid,
                "duration_min": duration_min,
                "thumb": thumbnail,
            }
            return track_details, vidid
            
        except Exception as e:
            logger.error(f"Error getting track details: {str(e)}")
            return default_track, ""

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced formats extraction without cookies"""
        try:
            if videoid:
                link = self.base + link
            
            # If not a URL, search first
            if not self.is_youtube_url(link):
                search_result = await self.search_youtube_with_ytdlp(link, 1)
                if search_result.get("result"):
                    link = search_result["result"][0].get("link", link)
            
            link = self.clean_url(link)
            
            ytdl_opts = {**self.base_ytdl_opts}
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
                                
                except yt_dlp.DownloadError as e:
                    logger.error(f"Format extraction failed: {str(e)}")
                    return [], link
                    
            return formats_available, link
        except Exception as e:
            logger.error(f"Error getting formats: {str(e)}")
            return [], link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        """Enhanced slider functionality"""
        try:
            if videoid:
                link = self.base + link
            
            search_result = await self.search_youtube_with_ytdlp(link, 10)
            result = search_result.get("result", [])
            
            if query_type < len(result):
                video = result[query_type]
                title = video.get("title", "Unknown")
                duration_min = video.get("duration", "0:00")
                vidid = video.get("id", "")
                thumbnail = video.get("thumbnails", [{}])[0].get("url", "").split("?")[0]
                return title, duration_min, thumbnail, vidid
            else:
                return "Unknown", "0:00", "", ""
        except Exception as e:
            logger.error(f"Error in slider: {str(e)}")
            return "Unknown", "0:00", "", ""

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
    ) -> str:
        """Enhanced download function without cookies and with search support"""
        try:
            if videoid:
                link = self.base + link
            
            # If not a URL, search first
            if not self.is_youtube_url(link):
                search_result = await self.search_youtube_with_ytdlp(link, 1)
                if search_result.get("result"):
                    link = search_result["result"][0].get("link", link)
                else:
                    logger.error("No search results found for download")
                    return None
            
            link = self.clean_url(link)
            loop = asyncio.get_running_loop()

            def audio_dl():
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": "bestaudio/best",
                    "outtmpl": "downloads/%(id)s.%(ext)s",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, False)
                if not info:
                    raise Exception("Failed to extract video info")
                
                file_ext = info.get('ext', 'mp3')  # Default to mp3 if ext not found
                xyz = os.path.join("downloads", f"{info['id']}.{file_ext}")
                
                if os.path.exists(xyz):
                    return xyz
                x.download([link])
                return xyz

            def video_dl():
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                    "outtmpl": "downloads/%(id)s.%(ext)s",
                    "merge_output_format": "mp4",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, False)
                if not info:
                    raise Exception("Failed to extract video info")
                
                file_ext = info.get('ext', 'mp4')  # Default to mp4 if ext not found
                xyz = os.path.join("downloads", f"{info['id']}.{file_ext}")
                
                if os.path.exists(xyz):
                    return xyz
                x.download([link])
                return xyz

            def song_video_dl():
                formats = f"{format_id}+140"
                fpath = f"downloads/{title}"
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": formats,
                    "outtmpl": fpath,
                    "prefer_ffmpeg": True,
                    "merge_output_format": "mp4",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                x.download([link])

            def song_audio_dl():
                fpath = f"downloads/{title}.%(ext)s"
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": format_id,
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

            if songvideo:
                await loop.run_in_executor(None, song_video_dl)
                fpath = f"downloads/{title}.mp4"
                return fpath
            elif songaudio:
                await loop.run_in_executor(None, song_audio_dl)
                fpath = f"downloads/{title}.mp3"
                return fpath
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
            
            return downloaded_file, direct
            
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            return None
