import asyncio
import os
import re
from typing import Union, Optional, Dict, List, Tuple
import logging
import yt_dlp
import json
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from pathlib import Path

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
        
        # Ensure downloads directory exists
        self.downloads_dir = Path("downloads")
        self.downloads_dir.mkdir(exist_ok=True)
        
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
            "default_search": "ytsearch",
        }

    def safe_duration_format(self, duration) -> str:
        """Safely format duration handling None, float, int, and string values"""
        try:
            if duration is None:
                return "0:00"
            
            if isinstance(duration, str):
                if duration == "None" or duration == "":
                    return "0:00"
                # If it's already formatted, return as is
                if ":" in duration:
                    return duration
                # Try to convert to number
                try:
                    duration = float(duration)
                except:
                    return "0:00"
            
            if isinstance(duration, (int, float)):
                duration = int(duration)  # Convert to int to avoid float issues
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
        except Exception as e:
            logger.error(f"Duration formatting error: {str(e)}")
            return "0:00"

    def clean_url(self, link: str) -> str:
        """Clean YouTube URL by removing unnecessary parameters"""
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

    async def robust_youtube_search(self, query: str, limit: int = 1):
        """Most robust YouTube search method"""
        try:
            if not query or query.strip() == "":
                return {"result": []}
            
            query = query.strip()
            
            # Method 1: Direct yt-dlp search (most reliable)
            loop = asyncio.get_running_loop()
            
            def search_with_ytdlp():
                try:
                    # If it's a URL, extract info directly
                    if self.is_youtube_url(query):
                        search_query = query
                    else:
                        # Use ytsearch for text queries
                        search_query = f"ytsearch{limit}:{query}"
                    
                    ytdl_opts = {
                        **self.base_ytdl_opts,
                        "extract_flat": True,
                        "skip_download": True,
                    }
                    
                    with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                        search_info = ydl.extract_info(search_query, download=False)
                        
                        if not search_info:
                            return None
                        
                        # Handle different response formats
                        entries = []
                        if "entries" in search_info and search_info["entries"]:
                            entries = [entry for entry in search_info["entries"] if entry is not None]
                        elif search_info.get("id"):
                            # Single video result
                            entries = [search_info]
                        
                        if not entries:
                            return None
                        
                        results = []
                        for entry in entries[:limit]:
                            if not entry or not entry.get("id"):
                                continue
                            
                            # Format duration safely
                            duration_str = self.safe_duration_format(entry.get("duration"))
                            
                            result_entry = {
                                "title": entry.get("title", "Unknown Title"),
                                "id": entry.get("id", ""),
                                "duration": duration_str,
                                "thumbnails": [{"url": entry.get("thumbnail", "")}],
                                "link": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                                "channel": {"name": entry.get("uploader", "Unknown Channel")},
                                "viewCount": {"text": str(entry.get("view_count", 0))}
                            }
                            results.append(result_entry)
                        
                        return {"result": results}
                        
                except Exception as e:
                    logger.error(f"yt-dlp search failed: {str(e)}")
                    return None
            
            # Execute search
            result = await loop.run_in_executor(None, search_with_ytdlp)
            
            if result and result.get("result"):
                return result
            
            # Method 2: Fallback with shell command
            logger.info("Trying fallback search method...")
            try:
                if self.is_youtube_url(query):
                    cmd = f'yt-dlp --dump-single-json --no-warnings --quiet "{query}"'
                else:
                    cmd = f'yt-dlp --dump-single-json --no-warnings --quiet "ytsearch1:{query}"'
                
                output = await shell_cmd(cmd)
                
                if output and not output.startswith("Error:"):
                    try:
                        info = json.loads(output)
                        duration_str = self.safe_duration_format(info.get("duration"))
                        
                        return {
                            "result": [{
                                "title": info.get("title", "Unknown Title"),
                                "id": info.get("id", ""),
                                "duration": duration_str,
                                "thumbnails": [{"url": info.get("thumbnail", "")}],
                                "link": f"https://www.youtube.com/watch?v={info.get('id', '')}",
                                "channel": {"name": info.get("uploader", "Unknown Channel")},
                                "viewCount": {"text": str(info.get("view_count", 0))}
                            }]
                        }
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.error(f"Fallback search failed: {str(e)}")
            
            # Method 3: Last resort - simple search
            logger.info("Trying final fallback...")
            if not self.is_youtube_url(query):
                cmd = f'yt-dlp --get-title --get-id --get-duration --no-warnings --quiet "ytsearch1:{query}"'
                output = await shell_cmd(cmd)
                
                if output and not output.startswith("Error:"):
                    lines = [line.strip() for line in output.split("\n") if line.strip()]
                    if len(lines) >= 2:
                        title = lines[0] if len(lines) > 0 else "Unknown"
                        video_id = lines[1] if len(lines) > 1 else ""
                        duration = lines[2] if len(lines) > 2 else "0:00"
                        
                        return {
                            "result": [{
                                "title": title,
                                "id": video_id,
                                "duration": duration,
                                "thumbnails": [{"url": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"}],
                                "link": f"https://www.youtube.com/watch?v={video_id}",
                                "channel": {"name": "Unknown Channel"},
                                "viewCount": {"text": "0"}
                            }]
                        }
            
            logger.error(f"All search methods failed for query: {query}")
            return {"result": []}
            
        except Exception as e:
            logger.error(f"Robust search completely failed: {str(e)}")
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
        """Enhanced video details using robust search"""
        try:
            if videoid:
                link = self.base + link
            
            search_result = await self.robust_youtube_search(link, 1)
            
            if not search_result.get("result"):
                return "Unknown", "0:00", 0, "", ""
            
            result = search_result["result"][0]
            
            title = result.get("title", "Unknown")
            duration_min = result.get("duration", "0:00")
            thumbnail = result.get("thumbnails", [{}])[0].get("url", "")
            if thumbnail and "?" in thumbnail:
                thumbnail = thumbnail.split("?")[0]
            vidid = result.get("id", "")
            
            # Convert duration to seconds
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
        """Enhanced title extraction"""
        try:
            details = await self.details(link, videoid)
            return details[0] if details else "Unknown"
        except Exception as e:
            logger.error(f"Error getting title: {str(e)}")
            return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced duration extraction"""
        try:
            details = await self.details(link, videoid)
            return details[1] if details else "0:00"
        except Exception as e:
            logger.error(f"Error getting duration: {str(e)}")
            return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        """Enhanced thumbnail extraction"""
        try:
            details = await self.details(link, videoid)
            return details[3] if details else ""
        except Exception as e:
            logger.error(f"Error getting thumbnail: {str(e)}")
            return ""

    async def video(self, link: str, videoid: Union[bool, str] = None):
        """Cookie-free video stream URL extraction with search support"""
        try:
            if videoid:
                link = self.base + link
            
            # Get proper URL if it's a search query
            if not self.is_youtube_url(link):
                search_result = await self.robust_youtube_search(link, 1)
                if search_result.get("result"):
                    link = search_result["result"][0].get("link", link)
                else:
                    return 0, "No search results found"
            
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
        """Enhanced track details with guaranteed return structure"""
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
            
            search_result = await self.robust_youtube_search(link, 1)
            
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
        """Enhanced formats extraction without cookies"""
        try:
            if videoid:
                link = self.base + link
            
            # Get proper URL if it's a search query
            if not self.is_youtube_url(link):
                search_result = await self.robust_youtube_search(link, 1)
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
            
            search_result = await self.robust_youtube_search(link, 10)
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
        """Create a safe filename by removing invalid characters"""
        if not filename:
            return "unknown"
        
        # Remove invalid characters
        safe_name = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Replace spaces and other characters
        safe_name = re.sub(r'[\s\-]+', '_', safe_name)
        # Limit length
        safe_name = safe_name[:100] if len(safe_name) > 100 else safe_name
        # Ensure it's not empty
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
    ) -> str:
        """Enhanced download function with robust file handling"""
        try:
            if videoid:
                link = self.base + link
            
            # Get proper URL and title if it's a search query
            if not self.is_youtube_url(link):
                search_result = await self.robust_youtube_search(link, 1)
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

            def audio_dl():
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": "bestaudio/best",
                    "outtmpl": str(self.downloads_dir / "%(id)s.%(ext)s"),
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, False)
                
                if not info:
                    raise Exception("Failed to extract video info")
                
                video_id = info.get('id', 'unknown')
                file_ext = info.get('ext', 'webm')  # Default extension
                
                # Try common audio extensions
                for ext in [file_ext, 'webm', 'mp4', 'm4a', 'opus']:
                    potential_file = self.downloads_dir / f"{video_id}.{ext}"
                    if potential_file.exists():
                        return str(potential_file)
                
                # Download if not exists
                x.download([link])
                
                # Find the downloaded file
                for ext in ['webm', 'mp4', 'm4a', 'opus']:
                    potential_file = self.downloads_dir / f"{video_id}.{ext}"
                    if potential_file.exists():
                        return str(potential_file)
                
                # Fallback
                return str(self.downloads_dir / f"{video_id}.{file_ext}")

            def video_dl():
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])/best[height<=?720]",
                    "outtmpl": str(self.downloads_dir / "%(id)s.%(ext)s"),
                    "merge_output_format": "mp4",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, False)
                
                if not info:
                    raise Exception("Failed to extract video info")
                
                video_id = info.get('id', 'unknown')
                file_ext = 'mp4'  # Force mp4 for videos
                
                potential_file = self.downloads_dir / f"{video_id}.{file_ext}"
                if potential_file.exists():
                    return str(potential_file)
                
                x.download([link])
                return str(potential_file)

            def song_video_dl():
                if not title:
                    safe_title = "unknown"
                else:
                    safe_title = self.safe_filename(str(title))
                
                formats = f"{format_id}+140" if format_id else "best"
                fpath = str(self.downloads_dir / f"{safe_title}.%(ext)s")
                
                ydl_optssx = {
                    **self.base_ytdl_opts,
                    "format": formats,
                    "outtmpl": fpath,
                    "prefer_ffmpeg": True,
                    "merge_output_format": "mp4",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                x.download([link])
                
                return str(self.downloads_dir / f"{safe_title}.mp4")

            def song_audio_dl():
                if not title:
                    safe_title = "unknown"
                else:
                    safe_title = self.safe_filename(str(title))
                
                fpath = str(self.downloads_dir / f"{safe_title}.%(ext)s")
                
                ydl_optssx = {
                    **self.base_ytdl_opts,
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
