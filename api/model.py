import re
import os
from datetime import timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ================== GLOBAL YOUTUBE CLIENT INITIALIZATION ==================
API_KEY = "AIzaSyBlUH-gxxX4tiJ8rK5Yinop-xHn1XXDI3w"  # ← REPLACE WITH YOUR KEY

try:
    youtube = build('youtube', 'v3', developerKey=API_KEY)
except Exception as e:
    raise RuntimeError(f"Failed to initialize YouTube API: {str(e)}")


def main():
    print("=== YouTube Playlist Scheduler ===")
    
    # Get playlist URL
    playlist_url = input("\nEnter YouTube playlist URL: ").strip()
    
    try:
        print("\nFetching playlist details...")
        videos = fetch_playlist_details(playlist_url)
        print(f"Found {len(videos)} videos")
        
        # Get scheduling preference
        while True:
            schedule_type = input("\nChoose scheduling method:\n1. Time-based (minutes per day)\n2. Day-based (number of days)\nEnter choice (1/2): ").strip()
            
            if schedule_type in ['1', '2']:
                break
            print("Invalid choice. Please enter 1 or 2.")
        
        schedule = None
        if schedule_type == '1':
            while True:
                try:
                    daily_time = int(input("\nEnter desired study time (minutes per day): "))
                    if daily_time > 0:
                        schedule = create_schedule_time_based(videos, daily_time)
                        break
                    print("Please enter a positive number.")
                except ValueError:
                    print("Please enter a valid number.")
        else:
            while True:
                try:
                    num_days = int(input("\nEnter number of days to complete the playlist: "))
                    if num_days > 0:
                        schedule = create_schedule_day_based(videos, num_days)
                        break
                    print("Please enter a positive number.")
                except ValueError:
                    print("Please enter a valid number.")
        
        # Print schedule summary
        print("\nSchedule Summary:")
        summary = get_schedule_summary(schedule)
        for key, value in summary.items():
            print(f"{key:20}: {value}")
        
        # Print detailed schedule
        print("\nDetailed Schedule:")
        for day, videos in schedule.items():
            total_duration = sum(parse_duration(v['duration']) for v in videos if v.get('duration') != "00:00:00")
            print(f"\n{day} (Total: {format_duration(total_duration)}):")
            for video in videos:
                if video.get('link'):  # Skip revision days
                    print(f"  - {video['title']} ({video['duration']})")
                else:
                    print(f"  - {video['title']}")
        
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        print("\nPossible solutions:")
        print("1. Check your internet connection")
        print("2. Verify the playlist URL is correct and accessible")
        print("3. Check API key validity")
        print("4. Try again later if the service is temporarily unavailable")


def validate_playlist_url(url):
    """Validate YouTube playlist URL format."""
    if not url:
        raise ValueError("Playlist URL cannot be empty")
    patterns = [
        r'youtube\.com/playlist\?list=',
        r'youtu\.be/.*\?list=',
        r'list='
    ]
    if not any(re.search(pattern, url) for pattern in patterns):
        raise ValueError("Invalid YouTube playlist URL format")
    return True


def extract_playlist_id(url):
    """Extract playlist ID from URL using multiple patterns."""
    patterns = [
        r'list=([a-zA-Z0-9_-]+)',
        r'youtu\.be/.*\?list=([a-zA-Z0-9_-]+)',
        r'/playlist/([a-zA-Z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError("Could not extract playlist ID from URL")


def format_duration(seconds):
    """Format seconds to HH:MM:SS with leading zeros."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def parse_iso_duration(duration_str):
    """Convert ISO 8601 duration to total seconds."""
    duration_str = duration_str.upper().replace('PT', '')
    total_seconds = 0
    time_components = {'H': 0, 'M': 0, 'S': 0}
    current_value = ''
    
    for char in duration_str:
        if char.isdigit():
            current_value += char
        elif char in time_components:
            time_components[char] = int(current_value) if current_value else 0
            current_value = ''
    
    return (time_components['H'] * 3600 
            + time_components['M'] * 60 
            + time_components['S'])


def parse_duration(duration_str):
    """Convert HH:MM:SS string to total seconds."""
    parts = list(map(int, duration_str.split(':')))
    multipliers = [3600, 60, 1]
    return sum(part * mult for part, mult in zip(parts[-3:], multipliers[-len(parts):]))


def fetch_playlist_details(playlist_url):
    """Fetch all video details from a YouTube playlist."""
    if not youtube:
        raise RuntimeError("YouTube API client not initialized")
    
    try:
        validate_playlist_url(playlist_url)
        playlist_id = extract_playlist_id(playlist_url)
        
        # Fetch all video IDs from playlist
        video_ids = []
        next_page_token = None
        
        while True:
            request = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()
            
            video_ids.extend([
                item['snippet']['resourceId']['videoId']
                for item in response.get('items', [])
            ])
            
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

        if not video_ids:
            raise ValueError("Playlist is empty or inaccessible")

        # Fetch video details in batches
        video_details = []
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i+50]
            
            videos_request = youtube.videos().list(
                part="snippet,contentDetails",
                id=",".join(batch_ids)
            )
            videos_response = videos_request.execute()
            
            for item in videos_response.get('items', []):
                try:
                    video_id = item['id']
                    duration = parse_iso_duration(item['contentDetails']['duration'])
                    video_details.append({
                        "title": item['snippet']['title'],
                        "duration": format_duration(duration),
                        # Updated link format to youtube.com/watch?v= instead of youtu.be/
                        "link": f"https://youtube.com/watch?v={video_id}",
                        "thumbnail": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                        "video_id": video_id
                    })
                except KeyError as e:
                    print(f"Skipping video due to missing data: {str(e)}")
                    continue

        return video_details

    except HttpError as e:
        error = e.error_details[0]['message']
        status = e.resp.status
        raise RuntimeError(
            f"YouTube API Error ({status}): {error}\n"
            "Common fixes:\n"
            "1. Check API key validity\n"
            "2. Verify YouTube Data API v3 is enabled\n"
            "3. Check API quota usage"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to fetch playlist: {str(e)}")


def create_schedule_time_based(video_details, daily_time_minutes):
    """Create schedule based on daily time limit."""
    daily_time_seconds = daily_time_minutes * 60
    schedule = {}
    current_day = 1
    current_videos = []
    current_duration = 0
    
    for video in video_details:
        duration = parse_duration(video['duration'])
        
        # If a single video is longer than daily limit, put it alone in a day
        if duration > daily_time_seconds:
            if current_videos:
                schedule[f"Day {current_day}"] = current_videos
                current_day += 1
            schedule[f"Day {current_day}"] = [video]
            current_day += 1
            current_videos = []
            current_duration = 0
            continue
        
        if current_duration + duration <= daily_time_seconds:
            current_videos.append(video)
            current_duration += duration
        else:
            schedule[f"Day {current_day}"] = current_videos
            current_day += 1
            current_videos = [video]
            current_duration = duration
    
    if current_videos:
        schedule[f"Day {current_day}"] = current_videos
    
    return schedule


def create_schedule_day_based(video_details, num_days):
    """Create schedule based on number of days."""
    schedule = {}
    
    if not video_details:
        return schedule
    
    total_duration = sum(parse_duration(v['duration']) for v in video_details)
    avg_daily = total_duration / num_days
    
    current_day = 1
    current_videos = []
    current_duration = 0
    
    for video in video_details:
        duration = parse_duration(video['duration'])
        
        if current_duration + duration > avg_daily and current_videos:
            schedule[f"Day {current_day}"] = current_videos
            current_day += 1
            current_videos = []
            current_duration = 0
            
            if current_day > num_days:
                break
        
        current_videos.append(video)
        current_duration += duration
    
    if current_videos and current_day <= num_days:
        schedule[f"Day {current_day}"] = current_videos
    
    # Add revision days if needed
    while current_day < num_days:
        current_day += 1
        schedule[f"Day {current_day}"] = [{
            "title": "Revision Day",
            "duration": "00:00:00",
            "link": None,
            "thumbnail": None
        }]
    
    return schedule


def get_schedule_summary(schedule):
    """Generate comprehensive schedule statistics."""
    total_days = len(schedule)
    study_days = sum(1 for day in schedule.values() if any(v.get('link') for v in day))
    
    total_videos = sum(
        len([v for v in day if v.get('link') is not None])
        for day in schedule.values()
    )
    
    total_seconds = sum(
        sum(parse_duration(v['duration']) for v in day if v.get('link'))
        for day in schedule.values()
    )
    
    return {
        "totalVideos": total_videos,
        "totalDays": total_days,
        "Study Days": study_days,
        "totalDuration": format_duration(total_seconds),
        "averageDailyDuration": format_duration(total_seconds // study_days) if study_days else "00:00:00"
    }


if __name__ == "__main__":
    main()