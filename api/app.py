# api/app.py - Part 1

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId
import os
from dotenv import load_dotenv
import google.generativeai as genai
from typing import Optional
import sys
import os

# Add parent directory to path to import model.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model import (
    fetch_playlist_details,
    create_schedule_time_based,
    create_schedule_day_based,
    validate_playlist_url,
    get_schedule_summary
)

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Updated CORS configuration for production
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:3000",
            "https://your-frontend-domain.vercel.app"  # Update with your frontend domain
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
        "max_age": 120
    }
})

# MongoDB connection
MONGO_URI = os.getenv('MONGODB_URI')
DB_NAME = os.getenv('DB_NAME', 'your_database_name')
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
schedules_collection = db.schedules

# Configure Gemini
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Helper Functions
def validate_object_id(id_string: str) -> bool:
    """Validate MongoDB ObjectId format"""
    try:
        ObjectId(id_string)
        return True
    except:
        return False

def format_schedule_response(schedule):
    """Format schedule for JSON response"""
    if not schedule:
        return None
    
    schedule['_id'] = str(schedule['_id'])
    schedule['userId'] = str(schedule['userId'])
    schedule['created_at'] = schedule['created_at'].isoformat()
    schedule['updated_at'] = schedule['updated_at'].isoformat()
    
    for day_schedule in schedule['schedule_data']:
        if isinstance(day_schedule['date'], datetime):
            day_schedule['date'] = day_schedule['date'].strftime('%Y-%m-%d')
    
    return schedule

def get_chat_prompt(message: str, video_title: Optional[str] = None, mode: str = 'general') -> str:
    """Generate appropriate prompt based on chat mode and context"""
    if mode == 'video':
        return f"""You are an AI tutor focusing specifically on the video: "{video_title}".
        Please answer the following question in the context of this video only: {message}
        If the question isn't directly related to this video, kindly remind the user that you're
        currently focused on discussing this specific video."""
    else:
        return f"""You are an AI learning assistant helping with educational content.
        Please answer the following question: {message}"""

def format_gemini_response(response) -> str:
    """Format and clean Gemini API response"""
    try:
        text = response.text.replace('```', '').strip()
        max_length = 1000
        if len(text) > max_length:
            text = text[:max_length] + "... (response truncated)"
        return text
    except Exception as e:
        return f"I apologize, but I encountered an error processing the response: {str(e)}"

# Middleware for handling preflight requests
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")  # Updated for Vercel
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
        response.headers.add("Access-Control-Allow-Credentials", "true")
        return response

# Error handling
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500# api/app.py - Part 2

@app.route('/api/schedules/detail/<schedule_id>', methods=['GET', 'OPTIONS'])
def get_schedule_detail(schedule_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        if not validate_object_id(schedule_id):
            return jsonify({'error': 'Invalid schedule ID format'}), 400

        schedule = schedules_collection.find_one({'_id': ObjectId(schedule_id)})
        
        if not schedule:
            return jsonify({'error': 'Schedule not found'}), 404

        formatted_schedule = format_schedule_response(schedule)
        return jsonify({'schedule': formatted_schedule})

    except Exception as e:
        print(f"Error fetching schedule: {str(e)}")
        return jsonify({'error': 'Failed to fetch schedule'}), 500

@app.route('/api/schedule', methods=['POST', 'OPTIONS'])
def create_schedule():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Extract request data
        user_id = data.get('userId')
        playlist_url = data.get('playlistUrl')
        schedule_type = data.get('scheduleType')
        title = data.get('title', 'Untitled Schedule')
        completed_videos = data.get('completedVideos', [])
        last_day_number = data.get('lastDayNumber', 0)
        completed_video_details = data.get('completedVideoDetails', [])

        # Validate required fields
        if not all([user_id, playlist_url, schedule_type]):
            return jsonify({'error': 'Missing required fields'}), 400

        # Validate playlist URL
        try:
            validate_playlist_url(playlist_url)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

        # Fetch video details
        try:
            video_details = fetch_playlist_details(playlist_url)
            if not video_details:
                return jsonify({'error': 'No videos found in playlist'}), 400
        except Exception as e:
            return jsonify({'error': f'Error fetching playlist: {str(e)}'}), 400

        # Generate schedule based on type
        if schedule_type == 'daily':
            try:
                daily_hours = float(data.get('dailyHours', 2))
                daily_minutes = int(daily_hours * 60)
                if daily_minutes <= 10:
                    return jsonify({'error': 'Daily study time must be greater than 10 minutes'}), 400
                
                schedule = create_schedule_time_based(
                    video_details=video_details,
                    daily_time_minutes=daily_minutes,
                    completed_videos=completed_videos,
                    last_day_number=last_day_number,
                    completed_video_details=completed_video_details
                )
                settings = {'daily_hours': daily_hours}
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        else:
            try:
                target_days = int(data.get('targetDays', 7))
                if target_days <= 0:
                    return jsonify({'error': 'Target days must be greater than 0'}), 400
                
                schedule = create_schedule_day_based(
                    video_details=video_details,
                    num_days=target_days,
                    completed_videos=completed_videos,
                    last_day_number=last_day_number,
                    completed_video_details=completed_video_details
                )
                settings = {'target_days': target_days}
            except ValueError as e:
                return jsonify({'error': str(e)}), 400

        # Format schedule for MongoDB
        schedule_doc = {
            'userId': ObjectId(user_id),
            'title': title,
            'playlist_url': playlist_url,
            'schedule_type': schedule_type,
            'settings': settings,
            'schedule_data': [
                {
                    'day': day,
                    'date': (datetime.now() + timedelta(days=int(day.split()[1]) - 1)).strftime('%Y-%m-%d'),
                    'videos': [{**video, 'completed': False} for video in videos]
                }
                for day, videos in schedule.items()
            ],
            'summary': get_schedule_summary(schedule),
            'status': 'active',
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }

        # Save to MongoDB
        result = schedules_collection.insert_one(schedule_doc)
        
        return jsonify({
            'message': 'Schedule created successfully',
            'scheduleId': str(result.inserted_id),
            'schedule': schedule,
            'summary': schedule_doc['summary']
        })

    except Exception as e:
        print(f"Error creating schedule: {str(e)}")
        return jsonify({'error': 'Failed to create schedule'}), 500

@app.route('/api/schedules/<schedule_id>/adjust', methods=['POST', 'OPTIONS'])
def adjust_schedule(schedule_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.json
        if not data or 'newDailyHours' not in data:
            return jsonify({'error': 'New daily hours required'}), 400

        if not validate_object_id(schedule_id):
            return jsonify({'error': 'Invalid schedule ID format'}), 400

        # Get the existing schedule
        schedule = schedules_collection.find_one({'_id': ObjectId(schedule_id)})
        if not schedule:
            return jsonify({'error': 'Schedule not found'}), 404

        # Get completed videos information
        completed_videos = []
        completed_video_details = []
        for day in schedule['schedule_data']:
            for video in day['videos']:
                if video.get('completed'):
                    completed_videos.append(video['link'])
                    completed_video_details.append(video)

        # Fetch video details from playlist URL
        try:
            video_details = fetch_playlist_details(schedule['playlist_url'])
            if not video_details:
                return jsonify({'error': 'No videos found in playlist'}), 400
        except Exception as e:
            return jsonify({'error': f'Error fetching playlist: {str(e)}'}), 400

        # Create new schedule structure with new daily hours
        daily_hours = float(data['newDailyHours'])
        daily_minutes = int(daily_hours * 60)
        
        new_schedule = create_schedule_time_based(
            video_details=video_details,
            daily_time_minutes=daily_minutes,
            completed_videos=completed_videos,
            completed_video_details=completed_video_details
        )

        # Format the new schedule data
        new_schedule_data = []
        current_date = datetime.now()
        
        for day, videos in new_schedule.items():
            day_number = int(day.split()[1])
            day_videos = []
            
            for video in videos:
                # Preserve completion status
                video_completed = video['link'] in completed_videos
                day_videos.append({**video, 'completed': video_completed})
            
            new_schedule_data.append({
                'day': day,
                'date': (current_date + timedelta(days=day_number - 1)).strftime('%Y-%m-%d'),
                'videos': day_videos
            })

        # Update the existing schedule
        update_result = schedules_collection.update_one(
            {'_id': ObjectId(schedule_id)},
            {
                '$set': {
                    'schedule_data': new_schedule_data,
                    'settings.daily_hours': daily_hours,
                    'summary': get_schedule_summary(new_schedule),
                    'updated_at': datetime.now()
                }
            }
        )

        if update_result.modified_count == 0:
            return jsonify({'error': 'Failed to update schedule'}), 500

        # Fetch the updated schedule
        updated_schedule = schedules_collection.find_one({'_id': ObjectId(schedule_id)})
        formatted_schedule = format_schedule_response(updated_schedule)

        return jsonify({
            'message': 'Schedule adjusted successfully',
            'schedule': formatted_schedule
        })

    except Exception as e:
        print(f"Error adjusting schedule: {str(e)}")
        return jsonify({'error': 'Failed to adjust schedule'}), 500# api/app.py - Part 3

@app.route('/api/schedules/<user_id>', methods=['GET', 'OPTIONS'])
def get_user_schedules(user_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        if not validate_object_id(user_id):
            return jsonify({'error': 'Invalid user ID format'}), 400

        schedules = list(schedules_collection.find({'userId': ObjectId(user_id)}))
        formatted_schedules = [format_schedule_response(schedule) for schedule in schedules]
        
        return jsonify({'schedules': formatted_schedules})
    except Exception as e:
        print(f"Error fetching user schedules: {str(e)}")
        return jsonify({'error': 'Failed to fetch schedules'}), 500

@app.route('/api/schedules/<schedule_id>/progress', methods=['PUT', 'OPTIONS'])
def update_video_progress(schedule_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.json
        if not data or 'videoId' not in data:
            return jsonify({'error': 'Video ID required'}), 400

        if not validate_object_id(schedule_id):
            return jsonify({'error': 'Invalid schedule ID format'}), 400

        video_id = data['videoId']
        completed = data.get('completed', True)
        
        result = schedules_collection.update_one(
            {
                '_id': ObjectId(schedule_id),
                'schedule_data.videos.link': video_id
            },
            {
                '$set': {
                    'schedule_data.$[].videos.$[video].completed': completed,
                    'updated_at': datetime.now()
                }
            },
            array_filters=[{'video.link': video_id}]
        )
        
        if result.matched_count == 0:
            return jsonify({'error': 'Schedule or video not found'}), 404
            
        return jsonify({'message': 'Progress updated successfully'})
    except Exception as e:
        print(f"Error updating progress: {str(e)}")
        return jsonify({'error': 'Failed to update progress'}), 500

@app.route('/api/schedules/<schedule_id>/verify-video', methods=['POST', 'OPTIONS'])
def verify_video(schedule_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.json
        if not data or 'videoTitle' not in data:
            return jsonify({'error': 'Video title required'}), 400

        if not validate_object_id(schedule_id):
            return jsonify({'error': 'Invalid schedule ID format'}), 400

        schedule = schedules_collection.find_one({
            '_id': ObjectId(schedule_id),
            'schedule_data.videos.title': data['videoTitle']
        })
        
        return jsonify({
            'exists': bool(schedule),
            'message': 'Video found in schedule' if schedule else 'Video not found in schedule'
        })

    except Exception as e:
        print(f"Error verifying video: {str(e)}")
        return jsonify({'error': 'Failed to verify video'}), 500

@app.route('/api/schedules/<schedule_id>/video-context/<video_title>', methods=['GET', 'OPTIONS'])
def get_video_context(schedule_id, video_title):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        if not validate_object_id(schedule_id):
            return jsonify({'error': 'Invalid schedule ID format'}), 400

        schedule = schedules_collection.find_one({
            '_id': ObjectId(schedule_id),
            'schedule_data.videos.title': video_title
        })
        
        if not schedule:
            return jsonify({'error': 'Video not found'}), 404

        video_info = None
        for day in schedule['schedule_data']:
            for video in day['videos']:
                if video['title'] == video_title:
                    video_info = video
                    break
            if video_info:
                break

        if not video_info:
            return jsonify({'error': 'Video details not found'}), 404

        return jsonify({
            'video': {
                'title': video_info['title'],
                'duration': video_info['duration'],
                'thumbnail': video_info['thumbnail'],
                'completed': video_info['completed']
            }
        })

    except Exception as e:
        print(f"Error fetching video context: {str(e)}")
        return jsonify({'error': 'Failed to fetch video context'}), 500

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.json
        if not data or 'message' not in data:
            return jsonify({'error': 'Message required'}), 400

        message = data.get('message')
        video_title = data.get('videoTitle')
        mode = data.get('mode', 'general')

        prompt = get_chat_prompt(message, video_title, mode)

        try:
            response = model.generate_content(prompt)
            formatted_response = format_gemini_response(response)
            
            return jsonify({
                'response': formatted_response,
                'status': 'success'
            })
        except Exception as e:
            return jsonify({
                'error': f'Error generating response: {str(e)}',
                'status': 'error'
            }), 500

    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        return jsonify({'error': 'Failed to process chat request'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        # Check MongoDB connection
        client.admin.command('ping')
        
        # Check Gemini API
        test_response = model.generate_content("Test connection")
        gemini_status = "connected"

        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'database_name': DB_NAME,
            'gemini_api': gemini_status,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        print(f"Health check error: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# Vercel requires a handler function
def handler(request):
    """Handle Vercel serverless function requests"""
    return app(request)

# Development server configuration
if os.getenv('VERCEL_ENV') != 'production':
    if __name__ == '__main__':
        # Verify environment variables
        required_vars = ['MONGODB_URI', 'GOOGLE_API_KEY']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
            print("Please check your .env file")
            exit(1)
        
        # Print startup information
        print("\n=== Starting LearnFast API Server ===")
        print(f"Database: {DB_NAME}")
        print(f"MongoDB URI: {MONGO_URI[:20]}..." if MONGO_URI else "MongoDB URI not set")
        print(f"Gemini API Key: {'*' * 20}" if GOOGLE_API_KEY else "Gemini API Key not set")
        print("\nAvailable Routes:")
        print("================")
        for rule in app.url_map.iter_rules():
            if rule.endpoint != 'static':
                print(f"{rule.rule} [{', '.join(rule.methods - {'OPTIONS', 'HEAD'})}]")
        print("\nServer is running in development mode")
        print("=====================================\n")
        
        app.run(debug=True, port=5000)