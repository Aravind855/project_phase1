from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse, FileResponse, StreamingHttpResponse, HttpResponseRedirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from hr_interview.forms import ResumeUploadForm, AnswerForm
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
import json
import os
import numpy as np
from django.conf import settings
from django.urls import reverse
from bson.json_util import dumps
from PIL import Image
import pytesseract
import google.generativeai as genai
import bcrypt
import random
from prettytable import PrettyTable
from pymongo import MongoClient
from django.conf import settings
from . import models 
from datetime import datetime
from urllib.parse import quote_plus
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import cv2
import time
# import pyaudio
import logging
import threading
from bs4 import BeautifulSoup
from .forms import LoginForm, CandidateSignupForm, RecruiterSignupForm , CandidateProfileForm , JobPostingForm , ScheduleInterviewForm

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

genai.configure(api_key="AIzaSyBMrdrqZzvYTCRXV3kFSf8gk3At0kK_NHU")  # REPLACE with your actual API key
model = genai.GenerativeModel("gemini-1.5-flash-8b")

def configure_model(api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash-8b")
    return model

audio_alert = False
audio_threshold = 15000  
stop_audio_detection = False  


client = MongoClient(settings.MONGODB_URI)
db = client[settings.DB_NAME]


def extract_text_from_image(image_path):
        try:
            image = Image.open(image_path)
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            print(f"Error extracting text from image: {e}")
            return None

def generate_greeting(model):
            # Get the current hour to determine the time of day
            current_hour = datetime.now().hour
            if current_hour < 12:
                time_of_day = "Good morning"
            elif current_hour < 18:
                time_of_day = "Good afternoon"
            else:
                time_of_day = "Good evening"

            # Updated prompt to include a time-based greeting
            prompt = f"""
            You are an HR your likely to start the interview
            Start the interview with a warm and friendly greeting to set a positive tone. 
            Begin by saying "{time_of_day}" and ask only introductory questions, without providing any answers. 
            Your task is only to ask questions. Ask only 1 question, such as:
            
            - "{time_of_day}, what is your name?"
            - "How are you feeling today?"
            - "Are you ready to start the interview?" 
            """

            response = model.generate_content(prompt)
            greeting_message = response.text.strip()
            return greeting_message

def generate_greetting(model, previous_questions=[]):
    # Get the answer to the previous question (if available)
    previous_answer = previous_questions[-1]['answer'] if previous_questions else ""

    prompt = f"""
    Based on the previous answer: "{previous_answer}", 
    the user has previously provided the name , now generate a message that should be smooth transition to the interview like before start asking the questions , makeing the candidate to feel comfortable 
    for example , "Are you excited to attend this interview?" , "how would you prepare for this interview?" 
    it should be in 1 or 2 lines, it should be like a question.
    Do not provide any answers; just ask the questions in a friendly and inviting way.
    """
    response = model.generate_content(prompt)
    greeting_message = response.text.strip()
    return greeting_message

def generate_greeeting2(model, previous_questions=[]): # Renamed for clarity
    # Get the answer to the previous question (if available)
    previous_answer = previous_questions[-1]['answer'] if previous_questions else ""

    prompt = f"""
    Based on the previous answer: "{previous_answer}", ask a question to smoothly transition into the interview, for example:
    - "ok thats great Let's begin with the first question." 
    It should be a transition in 1 or 2 lines.
    It should be like a question, like "lets start with the first question?".
    Do not provide any answers; just ask the questions in a friendly and inviting way.
    """
    response = model.generate_content(prompt)
    greeting_message = response.text.strip()
    return greeting_message

def generate_resume_question(model, resume_text, previous_questions=[]):
            previous_questions_str = " ".join(previous_questions)
            prompt = (
                f"""You are an HR interviewer tasked with conducting an interview for a candidate.
                The interview is for a fresher.
                You have the candidate's resume, which provides the following information: {resume_text}
                
                avoid generating questions similar to the previous questions 
                The previous questions were: {previous_questions_str}
                
                The questions should be in a 1 or 2 line , 
                dont ask any lenghty or complex questions , or multiple questions 
                
                Your task is to formulate a concise, specific question that targets a particular 
                skill, experience, or project mentioned in the resume. 
                Focus on understanding the depth of the candidate's involvement and the 
                challenges they faced in that specific area. 

                Do not ask open-ended questions or questions about their general career aspirations.
                Generate only one question. Ask questions in a short manner. Your task is to analyze 
                the resume content and check how well they have knowledge of the resume. Don't ask 
                any questions or concepts related to programming."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            return question

def generate_self_intro_question(model):
    prompt = (
        """You are an HR interviewer tasked with conducting an interview for a fresher candidate.
        
        Start the interview by asking the candidate to give a brief self-introduction.

        Your question should encourage the candidate to share relevant details about their educational background, 
        interests, any notable projects or internships, and reasons for pursuing this specific role. Do not mention the candidate's name.
        
        The question should be open-ended to allow the candidate to speak freely, 
        but it should not prompt them to discuss general career aspirations or unrelated personal details.
        
        Generate a single, concise question inviting the candidate to introduce themselves and highlight relevant experiences."""
    )
    response = model.generate_content(prompt)
    question = response.text.strip()
    return question

def generate_self_intro_follow_up_question(model, self_intro_answer, previous_follow_up_questions=[]):
    previous_questions_str = " ".join(previous_follow_up_questions)  # Keep track of prior follow-up questions

    prompt = (
        f"""You are conducting an interview and want to ask a follow-up question based on the candidate's self-introduction response.
        The interview is for a fresher.

        The candidate's initial self-introduction response was:
        '{self_intro_answer}'

        Your task is to craft a short, specific follow-up question that encourages the candidate to expand on a particular aspect
        of their self-introduction. The follow-up question should be based on any of the following:
        - If the candidate mentioned a *hobby* (like football or reading), ask why they enjoy it, how they got interested in it, or how it has helped them develop skills.
        - If the candidate mentioned their *education* (such as a BTech degree), ask about what subjects they found most interesting or challenging, or what they hope to achieve with this degree.
        - If the candidate mentioned an *internship* or *work experience*, ask about their specific role or what skills they learned during the experience, without referring to the name of the company. Focus on what they did in the internship or the field of work.
        - If the candidate mentioned a *project*, ask about the most interesting part of it or what challenges they faced while working on it.
        - If the candidate mentioned *skills* they possess, ask about how they learned that skill or how they applied it in real-world scenarios.

        The follow-up question should be concise (1 or 2 lines) and should not introduce new topics. Focus on gathering more details
        based on what the candidate shared in their self-introduction. The goal is to dive deeper into their experiences, skills, or hobbies
        without introducing unrelated topics or specifics that weren't mentioned."""
    )
    
    response = model.generate_content(prompt)
    question = response.text.strip()
    return question

def generate_follow_up_question(model, previous_question, previous_answer):
            prompt = (
                f"""You are conducting an interview and want to ask a follow-up question. The interview is for a fresher.

                The previous question you asked was:
                '{previous_question}'

                The candidate responded with:
                '{previous_answer}'
                
                The questions should be in a 1 or 2 line , 
                dont ask any lenghty or complex questions , or multiple questions 

                Craft a specific follow-up question that delves deeper into the candidate's 
                previous response. Aim to gather more details, examples, or insights.

                Avoid asking new questions or changing the topic. Focus on the information
                already provided in the previous question and answer."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            return question

def generate_project_question(model, resume_text, previous_questions=[]):
    previous_questions_str = " ".join(previous_questions)
    prompt = (
        f"""You are interviewing a candidate for a position that requires technical skills. 
        The interview is for a fresher. 
        The candidate has mentioned the following programming languages, skills, and projects in their resume:
        {resume_text}

        Avoid generating questions similar to the previous questions.
        The previous questions were: {previous_questions_str}
        
        The question should be concise (1 or 2 lines).
        Do not ask lengthy or complex questions, or multiple questions in a single prompt.
        Do not ask the candidate to write code or a program.
        
        Your task is to ask a question specifically related to a project mentioned on the candidate's resume 
        that involves one of the programming languages listed. Focus on understanding the candidate's experience 
        with using the language within the project, any challenges they encountered, or specific implementations 
        they handled using that language.

        Generate only one question to assess their technical understanding of the project and programming language used."""
    )
    response = model.generate_content(prompt)
    question = response.text.strip()
    return question.replace("*", "")

def generate_technical_question(model, resume_text, previous_questions=[]):
            previous_questions_str = " ".join(previous_questions)
            prompt = (
            f"""You are interviewing a candidate for a position that requires technical skills. 
                The interview is for a fresher. 
                The candidate has mentioned the following skills and experience in their resume:
                {resume_text}

                avoid generating questions similar to the previous questions 
                The previous questions were: {previous_questions_str}
                
                The questions should be in a 1 or 2 line , 
                dont ask any lenghty or complex questions , or multiple questions
                dont ask any questions to write the code or program
                the question should be in a short and concise manner
                
                Your task is to assess the candidate's understanding of fundamental programming concepts
                based on the information provided in their resume. 

                Generate a single, concise technical question that specifically targets these skills. 
                Do not ask questions about general problem-solving or soft skills, only focus on 
                evaluating their technical knowledge in the context of their resume."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            #return question
            return question.replace("*", "")

def generate_hr_question(model, previous_questions=[]):
            previous_questions_str = " ".join(previous_questions)
            prompt = (
                f"""You are an HR interviewer assessing a candidate's fit for a role. 
                The interview is for a fresher. 
                Your goal is to evaluate their work experience, soft skills, or career goals.

                avoid generating questions similar to the previous questions 
                The previous questions were: {previous_questions_str}
                
                The questions should be in a 1 or 2 line , 
                dont ask any lenghty or complex questions , or multiple questions

                Formulate a single behavioral question that encourages the candidate to provide 
                specific examples from their past experiences.

                Focus on areas like:
                - Teamwork and collaboration
                - Problem-solving and decision-making
                - Communication and interpersonal skills
                - Adaptability and resilience
                - Leadership or initiative-taking (if applicable to the role)

                Avoid asking generic or hypothetical questions."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            #return question
            return question.replace("*", "")
        
def generate_scenario_question(model, previous_questions=[]):
            previous_questions_str = " ".join(previous_questions)
            prompt = (
                f"""You are an interviewer assessing a candidate's problem-solving abilities and 
                critical thinking skills. The interview is for a fresher. 

                avoid generating questions similar to the previous questions 
                The previous questions were: {previous_questions_str}
                
                The scenorio should be simpler and shorter 
                dont ask any lenghty or complex questions , or multiple questions

                Create a realistic, work-related scenario that the candidate might encounter in 
                the role they are interviewing for. 

                The scenario should present a challenge or conflict that requires the candidate to:

                - Analyze the situation
                - Identify potential solutions
                - Consider the implications of their actions
                - Make a decision or recommendation

                Present the scenario and ask the candidate a single, open-ended question about
                how they would approach the situation."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            #return question
            return question.replace("*", "")

def generate_past_experience_question(model, previous_questions=[]):
            previous_questions_str = " ".join(previous_questions)
            prompt = (
                f"""You are an interviewer wanting to explore a candidate's past experiences and 
                how they have learned and grown professionally. The interview is for a fresher. 

                avoid generating questions similar to the previous questions 
                The previous questions were: {previous_questions_str}
                
                The questions should be in a 1 or 2 line , 
                dont ask any lenghty or complex questions , or multiple questions

                Formulate a single question that encourages the candidate to reflect on their 
                previous roles and share a specific example of a time when they:

                - Overcame a significant challenge
                - Made a notable accomplishment
                - Learned a valuable lesson 
                - Demonstrated growth or resilience 

                Focus on gaining insights into the candidate's problem-solving process, work ethic, 
                and ability to learn from their experiences."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            #return question
            return question.replace("*", "")

def generate_attitude_question(model, previous_questions=[]):
            previous_questions_str = " ".join(previous_questions)
            prompt = (
                f"""You are an interviewer trying to understand a candidate's work ethic, attitude,
                and how they respond to challenging situations. The interview is for a fresher. 

                avoid generating questions similar to the previous questions 
                The previous questions were: {previous_questions_str}
                
                the question should be in 1 or 2 line , dont ask any lengthy or complex questions , or multiple questions

                Formulate a single question that uncovers the candidate's approach to:

                - Handling pressure or stressful deadlines
                - Dealing with difficult feedback
                - Managing conflicts with colleagues
                - Maintaining motivation and positivity
                - Demonstrating a strong work ethic

                Focus on eliciting specific examples or anecdotes that reveal the candidate's 
                true attitude and approach. Avoid asking hypothetical or leading questions."""
            )
            response = model.generate_content(prompt)
            question = response.text.strip()
            #return question
            return question.replace("*", "")

def generate_closing(model, previous_questions=[]):
    previous_answer = previous_questions[-1]['answer'] if previous_questions else ""

    prompt = f"""
    Given the candidate's last response: "{previous_answer}", provide a closing message to thank the candidate for the interview. It should be 1 or 2 lines. Examples:
    - "Thank you for your insightful answers. We appreciate your time."
    - "It was a pleasure learning more about your experience. We'll be in touch soon."
    """
    response = model.generate_content(prompt)
    closing_message = response.text.strip()
    return closing_message

def analyze_question_relevance(model,question, answer):
        prompt = f"""
        Question: "{question}"
        Candidate's Answer: "{answer}"
        
        Analyze the answer based on the following categories and provide:
        - A numerical rating (from 1 to 10) for each category.
        - A brief explanation of why this rating was given.
        
        Categories:
        Act as a comprehensive evaluator with expertise as an HR professional, technical lead, and psychologist. Analyze the candidate's answer according to these aspects:
        
        1. Knowledge and Technical Competency: Does the candidate show a clear understanding of the subject? Rate from 1-10.
        2. Communication and Clarity: How clearly and effectively does the candidate communicate their thoughts? Rate from 1-10.
        3. Critical Thinking and Problem-Solving: Does the candidate demonstrate analytical or problem-solving abilities? Rate from 1-10.
        4. English Proficiency and Grammar: How proficient is the candidate's English language usage? Rate from 1-10.
        5. Presence of Mind and Attitude: Does the candidate show attentiveness, positivity, and a proactive mindset? Rate from 1-10.
        
        The explanation should not be more 10 words , it should be short and clear
        the rating should be only in integer , it should not be in float or like 3/10
        if the ratings are not applicable for specific category then you can use N/A 

        Please provide the output in a clean table format without any extra lines or dashes:

        | Category                          | Rating | Explanation         |
        | Knowledge and Technical Competency| Rating | Explanation         |
        | Communication and Clarity         | Rating | Explanation         |
        | Critical Thinking and Problem-Solving | Rating | Explanation     |
        | English Proficiency and Grammar   | Rating | Explanation         |
        | Presence of Mind and Attitude     | Rating | Explanation         |
        """
        response = model.generate_content(prompt)
        msg = response.text
        return msg.replace("*", "")

def calculate_average_ratings(ratings_explanations):
        category_ratings = {}
        for item in ratings_explanations:
            category = item[0]
            rating_str = item[1]
            try:
                rating = int(rating_str)  # Try converting to integer
                if 1 <= rating <= 10:  # Check if rating is within valid range
                    if category not in category_ratings:
                        category_ratings[category] = []
                    category_ratings[category].append(rating)
                else:
                    print(f"Invalid rating value (out of range): {rating_str} for category {category}")
            except ValueError:
                print(f"Invalid rating value (not an integer): {rating_str} for category {category}")

        average_ratings = {}
        for category, ratings in category_ratings.items():
            if ratings: # Check if the list is not empty
                average_ratings[category] = sum(ratings) / len(ratings)
            else:
                print(f"No valid ratings for category: {category}, assigning default 0")
                average_ratings[category] = 0 # or any other default you want


        return average_ratings

def calculate_final_rating(average_ratings):
        """Calculates a weighted final rating based on average category ratings."""
        weights = {
            "Knowledge and Technical Competency": 0.30,  # 30% weight
            "Communication and Clarity": 0.25,  # 25% weight
            "Critical Thinking and Problem-Solving": 0.20,  # 20% weight
            "English Proficiency and Grammar": 0.15,  # 15% weight
            "Presence of Mind and Attitude": 0.10,  # 10% weight
        }
        final_rating = 0
        for category, rating in average_ratings.items():
            final_rating += rating * weights.get(category, 0)  # Use 0 weight if category not found
        return round(final_rating, 2)

def parse_response(response):
        
        table_data = []
        lines = response.splitlines()
        
        for line in lines:
            # Check for table rows and exclude lines with --- or separators.
            if "|" in line and "---" not in line and "+" not in line and "category" not in line.lower() and "rating" not in line.lower() and "explanation" not in line.lower():
                # Split columns and strip whitespace
                columns = [col.strip() for col in line.split("|") if col.strip()]
                # Ensure it captures rows with exactly 3 columns (Category, Rating, Explanation)
                if len(columns) == 3:
                    table_data.append(columns)
        
        return table_data

def display_table(data, title="Analysis for Question"):
        table = PrettyTable()
        table.field_names = ["Category", "Rating", "Explanation"]
        table.add_rows(data)
        print(f"\n{title}:")
        print(table)

def get_overall_feedback(ratings_explanations):
        average_ratings = calculate_average_ratings(ratings_explanations)
        average_ratings_table = PrettyTable()
        average_ratings_table.field_names = ["Category", "Average Rating"]
        for category, rating in average_ratings.items():
            average_ratings_table.add_row([category, rating])
        average_ratings_html = average_ratings_table.get_html_string()

        print("\nAverage Ratings per Category:")
        print(average_ratings_table)

        final_rating = calculate_final_rating(average_ratings)  # Calculate final rating


        try:
            combined_feedback = "\n".join(
                [f"Category: {item[0]}, Rating: {item[1]}, Explanation: {item[2]}" for item in ratings_explanations]
            )

            prompt = f"""
            Based on the following individual ratings and explanations for each category:
            {combined_feedback}

            Provide a concise summary of the candidate's performance in a table format, including:
            - Overall Strengths
            - Overall Weaknesses
            - Hiring Recommendation (e.g., Strong Hire, Good Fit, Not Recommended)

            Table format:
            | Aspect | Description |
            |---|---|
            | Overall Strengths | ... |
            | Overall Weaknesses | ... |
            | Hiring Recommendation | ... |

            Keep the descriptions concise.
            """

            response = model.generate_content(prompt)
            response_text = response.text.replace("*", "")  # Extract and clean the text
            

            try:
                overall_feedback_table = PrettyTable()
                lines = response_text.splitlines()  # Split cleaned text into lines
                header_found = False
                for line in lines:
                    if "|" in line and "---" not in line and "+" not in line:
                        row_data = [cell.strip() for cell in line.split("|") if cell.strip()]
                        if len(row_data) == 2:
                            if not header_found:
                                overall_feedback_table.field_names = row_data
                                header_found = True
                            else:
                                overall_feedback_table.add_row(row_data)

                overall_feedback_html = overall_feedback_table.get_html_string()
                return average_ratings_html, overall_feedback_html, final_rating  # Return all three values

            except (IndexError, ValueError) as e:
                print(f"Error parsing overall feedback table: {e}")
                error_message = f"<p>Error parsing overall feedback: {e}</p>"  # HTML error message
                return average_ratings_html, error_message, final_rating  # Return HTML for error, final rating too

        except Exception as e:
            print(f"Error during overall feedback generation: {e}")
            error_message = "<p>Error occurred during overall feedback generation. Please try again.</p>"
            return average_ratings_html, error_message, final_rating

def parse_html_to_dict(html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        table_data = []
        table = soup.find('table')
        
        if table:
            headers = [th.text.strip() for th in table.find('thead').find_all('th')]
            rows = []
            for tr in table.find('tbody').find_all('tr'):
                row = {headers[i]: td.text.strip() for i, td in enumerate(tr.find_all('td'))}
                rows.append(row)
            table_data = {'headers': headers, 'rows': rows}
        return table_data

def gen_frames():
        global audio_alert, stop_audio_detection

        # Start audio detection thread
        # audio_thread = threading.Thread(target=audio_detection)
        # audio_thread.start()

        cap = cv2.VideoCapture(0,cv2.CAP_DSHOW)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

        if not cap.isOpened():
            print("Error: Camera access denied or not available.")
            yield (b'--frame\r\n'
                b'Content-Type: text/plain\r\n\r\nCamera access denied. Please check permissions.\r\n')

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Convert frame to grayscale for face detection
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # Detect faces in the frame
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

                # Add warnings for face and audio alerts
                if len(faces) > 1:
                    cv2.putText(frame, "WARNING: Multiple Faces Detected!", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                elif len(faces) == 0:
                    cv2.putText(frame, "WARNING: No Faces Detected!", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                
                if audio_alert:
                    cv2.putText(frame, "WARNING: Audio Detected!", (10, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

                # Encode frame for streaming
                ret, buffer = cv2.imencode('.jpg', frame)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        finally:
            # Release video resources and stop audio detection
            cap.release()
            stop_audio_detection = True
            # audio_thread.join()

def video_feed(request):
        return StreamingHttpResponse(gen_frames(), content_type='multipart/x-mixed-replace; boundary=frame')

def conduct_interview(model, resume_text, interview_type="general"):
    interview_data = []

    def add_question(question, answer=""):
        interview_data.append({"question": question, "answer": answer})

    # --- Common Initial Questions ---
    Q = generate_greeting(model)
    add_question(Q)

    # Get the first answer before generating the second question
    first_answer = next((q['answer'] for q in interview_data if q['question'] == Q), "") # Extract the answer to Q

    S = generate_greetting(model, [{"question": Q, "answer": first_answer}]) # Pass Q and its answer
    add_question(S)
    
    # Get the second answer before generating the third question
    second_answer = next((q['answer'] for q in interview_data if q['question'] == S), "") # Extract the answer to S

    R = generate_greeeting2(model, [{"question": S, "answer": second_answer}]) # Pass S and its answer (using the renamed function)
    add_question(R)

    asked_questions = [Q, S, R]

    if interview_type == "general":
        # --- General Interview Logic (copied from your original general_interview) ---
        q1 = generate_self_intro_question(model)  # Resume related questions in the general section
        add_question(q1)
        asked_questions.append(q1)  # Correctly updating asked_questions in general section

        q2 = generate_resume_question(model, resume_text, asked_questions)  # Generating a second resume-related question
        add_question(q2)
        asked_questions.append(q2)  # Correctly updating asked_questions in the general section

        follow_up_1 = generate_follow_up_question(model, q2, "")  # Follow-up question based on q2 in general section
        add_question(follow_up_1)
        asked_questions.append(follow_up_1)  # Correctly updating asked_questions in general section


        question_types = ["hr", "scenario", "past_experience", "attitude"]
        for question_type in question_types:
            question_function = globals()[f"generate_{question_type}_question"]
            question = question_function(model, asked_questions)  # General interview question generation for hr, scenario, experience, and attitude
            add_question(question)
            asked_questions.append(question)  # Correctly updating asked_questions in general section


    elif interview_type == "technical":
        # --- Technical Interview Logic (copied from your original technical_interview) ---
        R1 = generate_self_intro_question(model)
        add_question(R1)
        R2 = generate_self_intro_follow_up_question(model, "", asked_questions)  # Assuming this function takes an empty string and previous questions
        add_question(R2)
        q1 = generate_technical_question(model, resume_text, asked_questions)
        add_question(q1)
        q2 = generate_project_question(model, resume_text, [q1]+asked_questions)  # Make sure project question gets all asked questions as context
        add_question(q2)
        follow_up_1 = generate_follow_up_question(model, q2, "")
        add_question(follow_up_1)


        asked_questions = [R1, R2, q1, q2, follow_up_1]  # Reset asked_questions here because it should be reset before the below loop
        previous_answer = ""

        for _ in range(2):
            technical_question = generate_technical_question(model, resume_text, asked_questions)
            add_question(technical_question)
            asked_questions.append(technical_question)
            previous_answer = next((q['answer'] for q in interview_data if q['question'] == technical_question), "")
            follow_up_technical = generate_follow_up_question(model, technical_question, previous_answer)
            add_question(follow_up_technical)
            asked_questions.append(follow_up_technical)


        question_types = ["project"]
        for question_type in question_types:
            question_function = globals()[f"generate_{question_type}_question"]
            question = question_function(model, asked_questions)
            add_question(question)
            asked_questions.append(question)

    elif interview_type == "mixed":
        # --- Mixed Interview Logic (copied from your original mixed_interview) ---
        q1 = generate_self_intro_question(model)  # Resume questions also in mixed section (add asked_questions)
        add_question(q1)
        asked_questions.append(q1)  # Added q1 to asked_questions

        q2 = generate_resume_question(model, resume_text, asked_questions)
        add_question(q2)
        asked_questions.append(q2)  # Added q2 to asked_questions

        follow_up_1 = generate_follow_up_question(model, q2, "")
        add_question(follow_up_1)
        asked_questions.append(follow_up_1)

        asked_questions = [q1, q2, follow_up_1] # Removing this line might improve question diversity

        for _ in range(2):  # Technical and follow-up
            technical_question = generate_technical_question(model, resume_text, asked_questions)
            add_question(technical_question)
            asked_questions.append(technical_question)  # Appending technical questions to asked_questions
            previous_answer = next((q['answer'] for q in interview_data if q['question'] == technical_question), "")  # Getting the previous answer in the mixed section.
            follow_up_technical = generate_follow_up_question(model, technical_question, previous_answer)  # Generating follow-up questions in mixed section.
            add_question(follow_up_technical)  # Adding follow-up question to interview_data in mixed section.
            asked_questions.append(follow_up_technical)

        question_types = ["hr", "scenario", "past_experience", "attitude"]
        for question_type in question_types:
            question_function = globals()[f"generate_{question_type}_question"]
            question = question_function(model, asked_questions)
            add_question(question)
            asked_questions.append(question)


    # --- Common Closing ---
    closing_message = generate_closing(model,interview_data)
    add_question(closing_message)
    return interview_data

# ----- View Functions -----



def index(request, interview_type=None):
    if not interview_type:
        messages.error(request, "No interview type specified.")
        return redirect('home')
    if request.method == "POST":
        form = ResumeUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                file = form.cleaned_data['resume_image']
                # Process image in memory
                image = Image.open(file)
                resume_text = pytesseract.image_to_string(image)
                if not resume_text:
                    messages.error(request, "Could not extract text from resume.")
                    return redirect('index', interview_type=interview_type)

                # Conduct interview and store data
                interview_data = conduct_interview(model, resume_text, interview_type)
                
                # Store resume text and interview data in MongoDB
                interview_collection = db['interviews']
                interview_record = {
                    'user_id': request.user.id if request.user.is_authenticated else None,
                    'interview_type': interview_type,
                    'resume_text': resume_text,
                    'interview_data': interview_data,
                    'created_at': datetime.now()
                }
                interview_collection.insert_one(interview_record)

                request.session['interview_data'] = interview_data
                request.session['current_question'] = 0

                return redirect(reverse('question', kwargs={'interview_type': interview_type}))

            except Exception as e:
                logger.exception(f"Error in index view: {e}")
                messages.error(request, "An error occurred while processing the resume.")
                return redirect('index', interview_type=interview_type)
        else:
            messages.error(request, "Invalid file upload.")
            return redirect('index', interview_type=interview_type)
    else:
        form = ResumeUploadForm()
    return render(request, 'hr_interview/index.html', {'form': form, 'interview_type': interview_type})

def mixed_interview(request):
    return index(request, interview_type="mixed")

def technical_interview(request):
    return index(request, interview_type="technical")

def general_interview(request):
    return index(request, interview_type="general")

def question(request, interview_type):
    interview_data = request.session.get('interview_data')
    current_index = request.session.get('current_question')

    if not interview_data or current_index is None:
        messages.error(request, "Interview data not found.")
        return redirect('home')


    if request.method == "POST":
        logger.info(f"Received POST request: {request.POST}") # Log the POST data
        answer = request.POST.get("answer")
        logger.info(f"Answer received: {answer}")  # Log the extracted answer

        if not answer:
            logger.warning("Answer is empty!") # Log if answer is missing.
            return JsonResponse({'question': 'Please provide an answer.'}, status=400)
        
        interview_data[current_index]['answer'] = answer
        request.session['interview_data'] = interview_data

        request.session['current_question'] += 1

        if request.session['current_question'] >= len(interview_data):
            return JsonResponse({'message': 'Interview complete', 'redirect': reverse('results')})

        next_question_data = interview_data[request.session['current_question']]
        return JsonResponse({'question': next_question_data['question']})


    if current_index >= len(interview_data):
        return redirect('results')

    current_question_data = interview_data[current_index]
    return render(request, 'hr_interview/question.html', {
        'question': current_question_data['question'],
        'question_number': current_index + 1,
        'interview_type': interview_type 
    })
      
def results(request):
    from pymongo import MongoClient
    from django.conf import settings
    from bson.objectid import ObjectId

    # MongoDB setup using Atlas URI
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    results_collection = db['interview_results']

    # Retrieve session data
    interview_data = request.session.get('interview_data', [])

    if not interview_data:
        messages.error(request, "No interview data found.")
        return HttpResponseRedirect('/question')

    # Add index to interview data
    for i, item in enumerate(interview_data):
        item['index'] = i + 1

    questions_answers = [(item['question'], item['answer']) for item in interview_data]
    analysis_results_by_question = []

    for i, (question, answer) in enumerate(questions_answers):
        result = analyze_question_relevance(model, question, answer)
        table_data = parse_response(result)

        analysis_results_by_question.append({
            'question_number': i + 1,
            'analysis_results': table_data
        })

    ratings_explanations = [
        item for sublist in [analysis['analysis_results'] for analysis in analysis_results_by_question] for item in sublist
    ]

    if ratings_explanations:
        try:
            average_ratings_html, overall_feedback_text, final_rating = get_overall_feedback(ratings_explanations)
        except Exception as e:
            logging.error(f"Error in get_overall_feedback: {e}")
            average_ratings_html = ""
            overall_feedback_text = "<p>Error generating overall feedback.</p>"
            final_rating = 0
    else:
        average_ratings_html = ""
        overall_feedback_text = "<p>No feedback available. Please ensure questions have been answered.</p>"
        final_rating = 0

    # Convert HTML to structured data
    average_ratings_data = parse_html_to_dict(average_ratings_html)

    # Prepare data for MongoDB
    result_data = {
        'interview_responses': interview_data,
        'analysis_results_by_question': analysis_results_by_question,
        'overall_feedback': overall_feedback_text,
        'average_ratings_table': average_ratings_data,
        'final_rating': final_rating,
    }

    # Insert into MongoDB
    try:
        result_id = results_collection.insert_one(result_data).inserted_id
        messages.success(request, f"Results saved successfully with ID: {result_id}")
    except Exception as e:
        logging.error(f"Error saving to MongoDB: {e}")
        messages.error(request, "Failed to save results.")

    context = {
        'interview_responses': interview_data,
        'analysis_results_by_question': analysis_results_by_question,
        'overall_feedback': overall_feedback_text,
        'average_ratings_table': average_ratings_html,
        'final_rating': final_rating,
    }
    return render(request, 'hr_interview/results.html', context)


def home(request):
        return render(request, 'hr_interview/home.html')

def ai_interview_options(request):
        return render(request, 'hr_interview/ai_interview_options.html')

def login_view(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user_type = form.cleaned_data['user_type']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password'].encode('utf-8')

            collection = db['candidate_users'] if user_type == 'candidate' else db['recruiter_users']
            user = collection.find_one({'email': email})

            if user:
                stored_password = user['password'].encode('utf-8')
                if bcrypt.checkpw(password, stored_password):
                    request.session['user_type'] = user_type
                    request.session['user_email'] = email
                    redirect_url = '/candidate_dashboard/' if user_type == 'candidate' else '/recruiter_dashboard/'
                    messages.success(request, 'Login successful.')
                    return redirect(redirect_url)
                else:
                    messages.error(request, 'Invalid password.')
            else:
                messages.error(request, 'User not found.')
        else:
            messages.error(request, 'Invalid form data.')
    else:
        form = LoginForm()

    return render(request, 'hr_interview/login.html', {'form': form})

def candidate_signup(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    collection = db['candidate_users']

    if request.method == 'POST':
        form = CandidateSignupForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            if collection.find_one({'email': email}):
                messages.error(request, 'Email already registered.')
                return render(request, 'hr_interview/candidate_signup.html', {'form': form})

            password = form.cleaned_data['password'].encode('utf-8')
            hashed_password = bcrypt.hashpw(password, bcrypt.gensalt())

            user_data = {
                'name': form.cleaned_data['name'],
                'email': email,
                'phone_number': form.cleaned_data['phone_number'],
                'password': hashed_password.decode('utf-8'),
                'created_at': datetime.now()
            }

            try:
                collection.insert_one(user_data)
                messages.success(request, 'Signup successful. Please login.')
                return redirect('login')
            except Exception as e:
                logging.error(f"Error saving candidate to MongoDB: {e}")
                messages.error(request, 'Failed to save user data.')
        else:
            messages.error(request, 'Invalid form data.')
    else:
        form = CandidateSignupForm()

    return render(request, 'hr_interview/candidate_signup.html', {'form': form})

def recruiter_signup(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    collection = db['recruiter_users']

    if request.method == 'POST':
        form = RecruiterSignupForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            if collection.find_one({'email': email}):
                messages.error(request, 'Email already registered.')
                return render(request, 'hr_interview/recruiter_signup.html', {'form': form})

            password = form.cleaned_data['password'].encode('utf-8')
            hashed_password = bcrypt.hashpw(password, bcrypt.gensalt())

            user_data = {
                'company_name': form.cleaned_data['company_name'],
                'recruiter_name': form.cleaned_data['recruiter_name'],
                'email': email,
                'phone_number': form.cleaned_data['phone_number'],
                'password': hashed_password.decode('utf-8'),
                'created_at': datetime.now()
            }

            try:
                collection.insert_one(user_data)
                messages.success(request, 'Signup successful. Please login.')
                return redirect('login')
            except Exception as e:
                logging.error(f"Error saving recruiter to MongoDB: {e}")
                messages.error(request, 'Failed to save user data.')
        else:
            messages.error(request, 'Invalid form data.')
    else:
        form = RecruiterSignupForm()

    return render(request, 'hr_interview/recruiter_signup.html', {'form': form})

def candidate_dashboard(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    collection = db['candidate_users']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'candidate':
        messages.error(request, 'Please login as a candidate.')
        return redirect('login')

    user = collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    context = {
        'user': {
            'name': user['name'],
            'email': user['email'],
            'phone_number': user['phone_number']
        }
    }
    return render(request, 'hr_interview/candidate_dashboard.html', context)

def recruiter_dashboard(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    collection = db['recruiter_users']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'recruiter':
        messages.error(request, 'Please login as a recruiter.')
        return redirect('login')

    user = collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    context = {
        'user': {
            'recruiter_name': user['recruiter_name'],
            'company_name': user['company_name'],
            'email': user['email'],
            'phone_number': user['phone_number']
        }
    }
    return render(request, 'hr_interview/recruiter_dashboard.html', context)

def candidate_profile(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    collection = db['candidate_users']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'candidate':
        messages.error(request, 'Please login as a candidate.')
        return redirect('login')

    user = collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    if request.method == 'POST':
        form = CandidateProfileForm(request.POST)
        if form.is_valid():
            update_data = {
                'skills': form.cleaned_data['skills'],
                'experience': form.cleaned_data['experience'],
                'projects': form.cleaned_data['projects'],
                'updated_at': datetime.now()
            }
            try:
                collection.update_one(
                    {'email': user_email},
                    {'$set': update_data}
                )
                messages.success(request, 'Profile updated successfully.')
                return redirect('candidate_profile')
            except Exception as e:
                logging.error(f"Error updating candidate profile: {e}")
                messages.error(request, 'Failed to update profile.')
        else:
            messages.error(request, 'Invalid form data.')
    else:
        form = CandidateProfileForm(initial={
            'skills': user.get('skills', ''),
            'experience': user.get('experience', ''),
            'projects': user.get('projects', '')
        })

    context = {
        'user': {
            'name': user['name'],
            'email': user['email'],
            'phone_number': user['phone_number'],
            'skills': user.get('skills'),
            'experience': user.get('experience'),
            'projects': user.get('projects')
        },
        'form': form
    }
    return render(request, 'hr_interview/candidate_profile.html', context)

def candidate_dashboard(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    user_collection = db['candidate_users']
    interviews_collection = db['interviews']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'candidate':
        messages.error(request, 'Please login as a candidate.')
        return redirect('login')

    user = user_collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    interviews = list(interviews_collection.find({'candidate_email': user_email}).sort('scheduled_at', -1))

    context = {
        'user': {
            'name': user['name'],
            'email': user['email'],
            'phone_number': user['phone_number']
        },
        'interviews': interviews
    }
    return render(request, 'hr_interview/candidate_dashboard.html', context)

def manage_jobs(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    user_collection = db['recruiter_users']
    jobs_collection = db['jobs']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'recruiter':
        messages.error(request, 'Please login as a recruiter.')
        return redirect('login')

    user = user_collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    if request.method == 'POST':
        form = JobPostingForm(request.POST)
        if form.is_valid():
            job_data = {
                'title': form.cleaned_data['title'],
                'description': form.cleaned_data['description'],
                'location': form.cleaned_data['location'],
                'skills_required': form.cleaned_data['skills_required'],
                'company_name': user['company_name'],
                'recruiter_email': user_email,
                'created_at': datetime.now()
            }
            try:
                jobs_collection.insert_one(job_data)
                messages.success(request, 'Job posted successfully.')
                return redirect('manage_jobs')
            except Exception as e:
                logging.error(f"Error posting job: {e}")
                messages.error(request, 'Failed to post job.')
        else:
            messages.error(request, 'Invalid form data.')
    else:
        form = JobPostingForm()

    jobs = list(jobs_collection.find({'recruiter_email': user_email}).sort('created_at', -1))

    context = {
        'user': {
            'recruiter_name': user['recruiter_name'],
            'company_name': user['company_name'],
            'email': user['email'],
            'phone_number': user['phone_number']
        },
        'jobs': jobs,
        'form': form
    }
    return render(request, 'hr_interview/manage_jobs.html', context)

from bson.objectid import ObjectId

def explore_jobs(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    user_collection = db['candidate_users']
    jobs_collection = db['jobs']
    applications_collection = db['job_applications']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'candidate':
        messages.error(request, 'Please login as a candidate.')
        return redirect('login')

    user = user_collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    jobs = list(jobs_collection.find().sort('created_at', -1))
    applied_job_ids = [str(app['job_id']) for app in applications_collection.find({'candidate_email': user_email})]

    for job in jobs:
        job['id'] = str(job['_id'])
        job['applied'] = job['id'] in applied_job_ids

    context = {
        'user': {
            'name': user['name'],
            'email': user['email'],
            'phone_number': user['phone_number']
        },
        'jobs': jobs
    }
    return render(request, 'hr_interview/explore_jobs.html', context)

def apply_job(request, job_id):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    user_collection = db['candidate_users']
    jobs_collection = db['jobs']
    applications_collection = db['job_applications']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'candidate':
        messages.error(request, 'Please login as a candidate.')
        return redirect('login')

    user = user_collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    job = jobs_collection.find_one({'_id': ObjectId(job_id)})
    if not job:
        messages.error(request, 'Job not found.')
        return redirect('explore_jobs')

    existing_application = applications_collection.find_one({
        'candidate_email': user_email,
        'job_id': job_id
    })
    if existing_application:
        messages.warning(request, 'You have already applied for this job.')
        return redirect('explore_jobs')

    application_data = {
        'candidate_email': user_email,
        'candidate_name': user['name'],
        'candidate_phone': user['phone_number'],
        'candidate_skills': user.get('skills', ''),
        'candidate_experience': user.get('experience', ''),
        'candidate_projects': user.get('projects', ''),
        'job_id': job_id,
        'job_title': job['title'],
        'job_company': job['company_name'],
        'recruiter_email': job['recruiter_email'],
        'applied_at': datetime.now()
    }

    try:
        applications_collection.insert_one(application_data)
        messages.success(request, 'Job applied.')
    except Exception as e:
        logging.error(f"Error submitting application: {e}")
        messages.error(request, 'Failed to submit application.')

    return redirect('explore_jobs')

def view_candidates(request):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    user_collection = db['recruiter_users']
    applications_collection = db['job_applications']
    interviews_collection = db['interviews']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'recruiter':
        messages.error(request, 'Please login as a recruiter.')
        return redirect('login')

    user = user_collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    applications = list(applications_collection.find({'recruiter_email': user_email}).sort('applied_at', -1))
    for application in applications:
        application['job_id'] = str(application['job_id'])
        application['interview_scheduled'] = bool(interviews_collection.find_one({
            'candidate_email': application['candidate_email'],
            'job_id': application['job_id'],
            'recruiter_email': user_email
        }))

    context = {
        'user': {
            'recruiter_name': user['recruiter_name'],
            'company_name': user['company_name'],
            'email': user['email'],
            'phone_number': user['phone_number']
        },
        'applications': applications
    }
    return render(request, 'hr_interview/view_candidates.html', context)

def schedule_interview_direct(request, job_id, candidate_email):
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]
    user_collection = db['recruiter_users']
    jobs_collection = db['jobs']
    candidate_collection = db['candidate_users']
    interviews_collection = db['interviews']

    user_email = request.session.get('user_email')
    user_type = request.session.get('user_type')

    if not user_email or user_type != 'recruiter':
        messages.error(request, 'Please login as a recruiter.')
        return redirect('login')

    user = user_collection.find_one({'email': user_email})
    if not user:
        messages.error(request, 'User not found.')
        return redirect('login')

    job = jobs_collection.find_one({'_id': ObjectId(job_id)})
    if not job:
        messages.error(request, 'Job not found.')
        return redirect('view_candidates')

    candidate = candidate_collection.find_one({'email': candidate_email})
    if not candidate:
        messages.error(request, 'Candidate not found.')
        return redirect('view_candidates')

    existing_interview = interviews_collection.find_one({
        'candidate_email': candidate_email,
        'job_id': job_id,
        'recruiter_email': user_email
    })
    if existing_interview:
        messages.warning(request, 'Interview already scheduled for this candidate.')
        return redirect('view_candidates')

    interview_data = {
        'job_id': job_id,
        'job_title': job['title'],
        'company_name': job['company_name'],
        'candidate_email': candidate_email,
        'candidate_name': candidate['name'],
        'recruiter_email': user_email,
        'scheduled_at': datetime.now()
    }

    try:
        interviews_collection.insert_one(interview_data)
        messages.success(request, 'Interview scheduled.')
    except Exception as e:
        logging.error(f"Error scheduling interview: {e}")
        messages.error(request, 'Failed to schedule interview.')

    return redirect('view_candidates')