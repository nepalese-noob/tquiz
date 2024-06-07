import logging
import telebot
import json
import random
import threading
import time
from collections import defaultdict
from threading import Lock
import subprocess
import os
import requests
import socket
import re
from yt_dlp import YoutubeDL
from telebot import apihelper

# Configure logging
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Function to load or prompt for necessary configuration data
def load_or_prompt_data(filename, prompt_text):
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return file.read().strip()
    else:
        data = input(prompt_text)
        with open(filename, 'w') as file:
            file.write(data)
        return data

# Load or prompt for the bot token and group chat ID
API_TOKEN = load_or_prompt_data('token.txt', 'Enter your Telegram bot token: ')
GROUP_CHAT_ID = load_or_prompt_data('groups.txt', 'Enter your group chat ID: ')
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
points_lock = Lock()

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
        bot.send_message(chat_id, f"Server is running at: {serveo_url} - Increase your points by answering the questions quickly. alternatively you can also practise your quiz from the below website but their points will not be shown here: www.nepalesenoob.free.nf")

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
    bot.reply_to(message, "Welcome! I'm your quiz bot.")

# Handler for /getlink command
@bot.message_handler(commands=['getlink'])
def send_link(message):
    start_php_server_on_available_port(message.chat.id)

# Handler for /stoplink command
@bot.message_handler(commands=['stoplink'])
def stop_link(message):
    stop_php_server(message.chat.id)

# Handler for new polls
@bot.message_handler(content_types=['poll'])
def handle_new_poll_message(message):
    handle_new_poll(message.poll, message.chat.id, message.from_user.id)

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

# Function to send random quiz every 60 seconds
def send_random_quiz(chat_id):
    quiz_questions, sent_questions = load_data()
    valid_questions = [q for q in quiz_questions['questions'] if q.get('correct_option') is not None and q not in sent_questions]

    while valid_questions:
        question = random.choice(valid_questions)
        if len(question['options']) < 2:
            logging.error("Error: Quiz must have at least 2 options.")
            continue

        # Check if 'correct_option' is a string and if it's a digit, then convert to int
        correct_option = question['correct_option']
        if isinstance(correct_option, str):
            correct_option = correct_option.strip("'").strip()  # Remove apostrophes and whitespace
            if correct_option.lower() == 'null' or correct_option == '':
                correct_option = None
            elif correct_option.isdigit():
                correct_option = int(correct_option)
            else:
                logging.error(f"Error: Invalid correct_option format: {correct_option}")
                continue
        elif not isinstance(correct_option, int):
            logging.error(f"Error: correct_option must be an integer or a string representing an integer, got {type(correct_option)}")
            continue

        if correct_option is None or correct_option >= len(question['options']):
            logging.error(f"Error: Invalid correct_option value: {correct_option}")
            continue

        # Remove trailing comma from options if present
        options = [option.rstrip(',') for option in question['options']]
        bot.send_poll(chat_id, question['question'], options, type='quiz', correct_option_id=correct_option, explanation=question.get('explanation', ''))

        # Append the sent question to sent_questions
        sent_questions.append(question)
        save_sent_data(sent_questions)

        # Sleep for 60 seconds before sending the next quiz
        time.sleep(60)

# Start a thread to send random quizzes
def start_quiz_thread():
    quiz_thread = threading.Thread(target=send_random_quiz, args=(GROUP_CHAT_ID,))
    quiz_thread.daemon = True
    quiz_thread.start()

# Handler for /randomquiz command
@bot.message_handler(commands=['randomquiz'])
def start_random_quiz(message):
    bot.reply_to(message, "Random quizzes will be sent every 60 seconds.")
    start_quiz_thread()

# Handler for /listpoints command
@bot.message_handler(commands=['listpoints'])
def list_points(message):
    with points_lock:
        points_list = sorted(points_data.items(), key=lambda x: x[1], reverse=True)
        response = "Points List:\n" + "\n".join([f"{bot.get_chat(int(user_id)).first_name}: {points}" for user_id, points in points_list])
    bot.reply_to(message, response)

# Start polling for messages
bot.polling(none_stop=True)
    
