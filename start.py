import logging
import telebot
import json
import threading
import time
from collections import defaultdict
import subprocess
import socket
import os
from yt_dlp import YoutubeDL
from telebot import apihelper

# Configure logging
logging.basicConfig(
    filename='bot.log', 
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Function to fetch or prompt for configuration data
def fetch_or_prompt_for_data(file_name, prompt_message):
    if os.path.exists(file_name):
        with open(file_name, 'r') as file:
            data = file.read().strip()
    else:
        data = input(prompt_message)
        with open(file_name, 'w') as file:
            file.write(data)
    return data

# Fetch or prompt for the bot token
API_TOKEN = fetch_or_prompt_for_data('token.txt', 'Please enter your bot API token: ')
# Fetch or prompt for the Telegram group chat ID
GROUP_CHAT_ID = fetch_or_prompt_for_data('groups.txt', 'Please enter your Telegram group chat ID: ')

# Initialize the bot
bot = telebot.TeleBot(API_TOKEN)

# Load or initialize quiz data
try:
    with open('quiz.json', 'r') as file:
        quiz_data = json.load(file)
except FileNotFoundError:
    quiz_data = {'questions': []}

# Load or initialize points data
try:
    with open('points.json', 'r') as file:
        points_data = json.load(file)
except FileNotFoundError:
    points_data = defaultdict(int)

# Lock for thread-safe operations on points_data
points_lock = threading.Lock()

# Function to save quiz data to file
def save_quiz_data():
    with open('quiz.json', 'w') as file:
        json.dump(quiz_data, file, indent=4)

# Function to save points data to file
def save_points_data():
    try:
        with open('points.json', 'w') as file:
            json.dump(dict(points_data), file, indent=4)
        logging.info("Points data saved successfully.")
    except Exception as e:
        logging.error(f"Failed to save points data: {e}")

def load_data():
    with open('quiz.json', 'r') as quiz_file:
        quiz_questions = json.load(quiz_file)
    try:
        with open('sent.json', 'r') as sent_file:
            sent_questions = json.load(sent_file)
    except FileNotFoundError:
        sent_questions = []
    return quiz_questions, sent_questions

# Save the sent questions data
def save_sent_data(sent_questions):
    with open('sent.json', 'w') as sent_file:
        json.dump(sent_questions, sent_file, indent=4)

# Define global variables
php_server_process = None
serveo_process = None
serveo_url = None
initial_port = 8084  # Initial port for PHP server

# Function to check if a port is available
def is_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) != 0

# Function to start the PHP server and get the Serveo link
def start_php_server_and_get_link(chat_id, port):
    global php_server_process, serveo_process, serveo_url

    try:
        # Start PHP server
        php_server_process = subprocess.Popen(f"php -S 127.0.0.1:{port} > bot.log 2>&1", shell=True)

        # Start an SSH session to Serveo to expose the PHP server
        serveo_process = subprocess.Popen(["ssh", "-R", f"{port}:localhost:{port}", "serveo.net"], stdout=subprocess.PIPE)

        # Wait for Serveo to start and get the public URL
        time.sleep(5)  # Adjust delay based on Serveo startup time
        serveo_url = serveo_process.stdout.readline().decode().strip().split()[-1]  # Extract the Serveo URL from stdout

        # Send the server link
        bot.send_message(chat_id, f"Server is running at: {serveo_url} - Increase your points by answering the questions quickly. Alternatively, you can also practice your quiz from the below website, but their points will not be shown here: www.nepalesenoob.free.nf")

        # Wait for a few seconds before sending the next message
        time.sleep(2)

        # Send the instruction to stop serving the link
        bot.send_message(chat_id, "To stop the server, use /stoplink command.")

    except Exception as e:
        logging.error(f"Error while starting the server: {e}")
        bot.send_message(chat_id, "Error: Failed to start the server.")

# Function to start the PHP server on an available port
def start_php_server_on_available_port(chat_id):
    port = initial_port
    while True:
        if is_port_available(port):
            start_php_server_and_get_link(chat_id, port)
            break
        else:
            port += 1

# Function to stop the PHP server and Serveo process
def stop_php_server(chat_id):
    global php_server_process, serveo_process, serveo_url

    try:
        # Terminate PHP server process
        php_server_process.terminate()

        # Terminate Serveo process
        serveo_process.terminate()

        # Inform the user that the server has stopped
        bot.send_message(chat_id, "Server has been stopped.")
    except Exception as e:
        logging.error(f"Error while stopping the server: {e}")
        bot.send_message(chat_id, "Error: Failed to stop the server.")

# Handler for /start command
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Welcome to the quiz bot! Use /getlink to start the PHP server and get the Serveo link.")

# Handler for /getlink command
@bot.message_handler(commands=['getlink'])
def send_link(message):
    start_php_server_on_available_port(message.chat.id)

# Handler for /stoplink command
@bot.message_handler(commands=['stoplink'])
def stop_link(message):
    stop_php_server(message.chat.id)

# Function to handle new polls and extract quiz data
def handle_new_poll(poll, chat_id, user_id):
    if poll.type == 'quiz':  # Check if the poll is a quiz
        question = poll.question
        options = [option.text for option in poll.options]
        # Set correct_option to None if not provided
        correct_option = poll.correct_option_id if poll.correct_option_id is not None else None
        explanation = poll.explanation if poll.explanation else ""

        # Check if the quiz already exists in quiz_data
        existing_quizzes = [(q['question'], q['options'], q['correct_option'], q['explanation']) for q in quiz_data['questions']]
        if (question, options, correct_option, explanation) not in existing_quizzes:
            new_quiz = {
                "question": question,
                "options": options,
                "correct_option": correct_option,
                "explanation": explanation
            }
            quiz_data['questions'].append(new_quiz)
            save_quiz_data()

            # Get user's name
            user_name = bot.get_chat(user_id).first_name
            if bot.get_chat(user_id).last_name:
                user_name += " " + bot.get_chat(user_id).last_name

            # Update points for submitting a new quiz
            with points_lock:
                # Initialize user points to 10 if not present, otherwise increment by 10
                points_data[str(user_id)] = points_data.get(str(user_id), 0) + 10
                save_points_data()

            # Send a message indicating that the quiz has been saved automatically
            bot.send_message(chat_id, f"The quiz has been saved automatically, and {user_name} has earned 10 points.")
        else:
            bot.send_message(chat_id, "This quiz is already saved.")

# Handler for /dm command to delete a message
@bot.message_handler(commands=['dm'])
def delete_message(message):
    # Check if the message is a reply
    if message.reply_to_message:
        # Delete the replied message
        bot.delete_message(message.chat.id, message.reply_to_message.message_id)
        # Delete the command message after 1 second
        time.sleep(1)
        bot.delete_message(message.chat.id, message.message_id)
    else:
        bot.send_message(message.chat.id, "Please reply to a message that you want to delete.")
@bot.message_handler(commands=['progress'])
def send_progress(message):
    # Load points data from points.json manually
    try:
        with open('points.json', 'r') as file:
            points_data = json.load(file)
    except FileNotFoundError:
        points_data = {}

    # Sort users by points
    sorted_points = sorted(points_data.items(), key=lambda item: item[1], reverse=True)
    progress_message = "<b>Progress:</b>\n"
    for index, (user_id, points) in enumerate(sorted_points[:21]):  # Show medals for up to 21 users
        rank = index + 1  # Calculate rank number
        if index == 0:
            medal = "🥇"
        elif index == 1:
            medal = "🥈"
        elif index == 2:
            medal = "🥉"
        else:
            # Use HTML <b> tags for ranks after 3
            medal = f"<b>{rank}.</b>"

        # Attempt to fetch user's full name, then first name, else use user ID
        user_name = str(user_id)  # Default to user ID
        try:
            user_info = bot.get_chat(user_id)
            if user_info.first_name and user_info.last_name:
                user_name = f"{user_info.first_name} {user_info.last_name}"  # Full name
            elif user_info.first_name:
                user_name = user_info.first_name  # First name only
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 400:
                logging.error(f"Chat not found for user_id: {user_id}")
                # Do not skip this user, user ID will be used as the name

        # Format the message with bold username and bold rank (if applicable)
        progress_message += f"{medal} <b>{user_name}</b>: {points} points\n"
    progress_message += "\nMake and send questions to earn points and become well-known!"

    # Send the progress message as a message with HTML formatting
    bot.send_message(message.chat.id, progress_message, parse_mode="HTML")



# Existing command handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome! I'm your quiz bot.")
# Existing command handlers
@bot.message_handler(commands=['totalquiz'])
# Existing command handlers
@bot.message_handler(commands=['totalquiz'])
def total_quiz(message):
    # Load questions from quiz.json
    with open('quiz.json', 'r') as file:
        quiz_data = json.load(file)
    total_questions = len(quiz_data['questions'])
    bot.reply_to(message, f"The number of quizzes in my bin: count within.\nTotal: <b>{total_questions}</b>", parse_mode="HTML")

@bot.message_handler(commands=['quiz'])
def send_quiz(message):
    while True:
        try:
            # Load questions from quiz.json
            with open('quiz.json', 'r') as file:
                quiz_data = json.load(file)
            # Select a random question
            question = random.choice(quiz_data['questions'])
            # Send the question as a poll
            correct_option_id = None
            if question['correct_option'] is not None:
                correct_option_id = int(question['correct_option'])
            bot.send_poll(
                chat_id=message.chat.id,
                question=question['question'],
                options=question['options'],
                is_anonymous=False,
                type='quiz',
                correct_option_id=correct_option_id,
                explanation=question['explanation']
            )
            break  # Exit the loop if the poll is sent successfully
        except telebot.apihelper.ApiTelegramException as e:
            # If there's an error with sending the poll, log the error and try another question
            print(f"Error sending poll: {e}")
            continue
# Start the bot
if __name__ == '__main__':
    bot.polling(none_stop=True)
    
