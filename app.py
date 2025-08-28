# ======================================================================================
# FINAL APP.PY - DEFINITIVE UI
# ======================================================================================

import streamlit as st
import sqlite3
import hashlib
from datetime import datetime
import requests
import pandas as pd
import google.generativeai as genai
import time
import re

# --- Page Configuration ---
st.set_page_config(
    page_title="Career Mentor By Taha",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Function to load CSS ---
def load_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except FileNotFoundError:
        st.error(f"CSS file not found. Please make sure `style.css` is in the same directory as `app.py`.")

load_css("style.css")


# ======================================================================================
# DATABASE LOGIC
# ======================================================================================
DB_NAME = "users_v5.db" # Using a new DB file for the new structure

@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    return conn

# --- UPDATED: init_db now creates a ratings table ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, fullname TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT "user")')
    c.execute("SELECT * FROM users WHERE email = ?", ('admin@example.com',))
    if c.fetchone() is None:
        admin_pass_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        c.execute("INSERT INTO users (fullname, email, password_hash, role) VALUES (?, ?, ?, ?)", ('Admin User', 'admin@example.com', admin_pass_hash, 'admin'))
    
    # NEW: Create the ratings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            rating INTEGER NOT NULL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_email) REFERENCES users (email)
        )
    ''')
    conn.commit()

def add_user(fullname, email, password):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("INSERT INTO users (fullname, email, password_hash) VALUES (?, ?, ?)", (fullname, email, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError: return False

def check_user(email, password):
    conn = get_db_connection()
    c = conn.cursor()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    c.execute("SELECT fullname, role FROM users WHERE email = ? AND password_hash = ?", (email, password_hash))
    return c.fetchone()

def get_all_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, fullname, email, role FROM users")
    return c.fetchall()

# --- NEW: Functions to handle ratings ---
def add_rating(user_email, rating_value):
    """Saves a user's rating to the database."""
    conn = get_db_connection()
    c = conn.cursor()
    rating_int = len(rating_value) # Convert '⭐⭐⭐' to 3
    c.execute("INSERT INTO ratings (user_email, rating) VALUES (?, ?)", (user_email, rating_int))
    conn.commit()

def get_all_ratings():
    """Fetches all ratings for the admin dashboard."""
    conn = get_db_connection()
    c = conn.cursor()
    # Join with users table to get the user's full name, which is more user-friendly
    c.execute("""
        SELECT r.id, u.fullname, r.user_email, r.rating, r.submitted_at
        FROM ratings r
        JOIN users u ON r.user_email = u.email
        ORDER BY r.submitted_at DESC
    """)
    return c.fetchall()


# ======================================================================================
# AI & TOOLS LOGIC
# ======================================================================================

@st.cache_data(ttl=3600)
def get_fields_from_gemini(interest_text):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""Based on the user's interest in '{interest_text}', suggest 4 specific and diverse career fields. Return the answer ONLY as a Python list of strings."""
        response = model.generate_content(prompt)
        match = re.search(r'\[.*?\]', response.text.replace('`', ''))
        if match: return eval(match.group())
        else: return ["Could not determine fields, please try a different interest."]
    except Exception as e:
        st.error(f"Error communicating with Gemini: {e}")
        return []

@st.cache_data(ttl=3600)
def get_gemini_guidance(interests, field):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""You are 'Mentor', an expert career AI. Generate an inspiring and detailed career guide for a student interested in '{field}', with interests in '{interests}'. Use markdown and emojis. Include these sections: 🚀 Why Your Interests Are a Perfect Match, 🗺️ Your 6-Month Kickstart Roadmap, 🌟 A Word of Encouragement."""
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"An error occurred while communicating with the Gemini API. Details: {e}")
        return None

@st.cache_data(ttl=3600)
def get_gemini_roadmap_interactive(field):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Create a detailed, step-by-step career roadmap for a '{field}'. The tone must be encouraging, professional, and clear for a student. Format the output using markdown. Use emojis for each phase title.
        **CRITICAL:** Structure the response into exactly 4 phases, each with a title like this: '### 🎓 Phase 1: Title'.
        Inside each phase, include these EXACT subheadings with bolding:
        - **Timeline:** (e.g., 6-12 Months)
        - **Key Skills to Acquire:** (A short bulleted list of essential technical and soft skills)
        - **Recommended Projects:** (A numbered list of 1-2 project ideas to build a portfolio)
        - **Networking & Growth:** (A short bulleted list of tips, like joining communities or finding a mentor)
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"An error occurred while generating the roadmap. Details: {e}")
        return None

def parse_and_display_roadmap(roadmap_content):
    phases = re.split(r'### (.*?)\n', roadmap_content)
    if len(phases) > 1:
        for i in range(1, len(phases), 2):
            phase_title = phases[i]
            phase_details = phases[i+1]
            with st.expander(phase_title):
                st.markdown(phase_details, unsafe_allow_html=True)

def get_real_world_jobs(query):
    try:
        api_key = st.secrets["JSEARCH_API_KEY"]
        url = "https://jsearch.p.rapidapi.com/search"
        querystring = {"query": query, "page": "1", "num_pages": "1"}
        headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        response = requests.get(url, headers=headers, params=querystring, timeout=20)
        response.raise_for_status()
        results = response.json()
        if "data" in results and results["data"]:
            job_listings = [{"Title": job.get("job_title"), "Company": job.get("employer_name"), "Location": f"{job.get('job_city', '')}, {job.get('job_state', '')}".strip(", "), "Link": job.get("job_apply_link")} for job in results["data"][:20]]
            return pd.DataFrame(job_listings)
        return pd.DataFrame()
    except requests.exceptions.Timeout:
        st.error("The job search request timed out. The server might be busy. Please try again in a moment.")
        return None
    except Exception as e:
        st.error(f"An error occurred while fetching jobs: {e}")
        return None

# ======================================================================================
# MAIN APPLICATION LOGIC & UI
# ======================================================================================

init_db()

if "page" not in st.session_state: st.session_state.page = "login"

def login_page():
    st.title("Welcome to the Career Mentor By Taha ✨")
    st.markdown('<h3 class="subtitle">Your personal guide to a successful future.</h3>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.header("Login")
        st.text_input("Email", key="login_email")
        st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            user_data = check_user(st.session_state.login_email, st.session_state.login_pass)
            if user_data:
                st.session_state.logged_in = True
                st.session_state.fullname = user_data[0]
                st.session_state.role = user_data[1]
                # --- NEW: Store email in session state for rating ---
                st.session_state.email = st.session_state.login_email
                st.session_state.page = "home"
                st.rerun()
            else:
                st.error("Invalid email or password")
        st.markdown('</div>', unsafe_allow_html=True)

def signup_page():
    st.title("Create Your Account ✨")
    st.markdown('<h3 class="subtitle">Join our community and start planning your career.</h3>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.header("Sign Up")
        st.text_input("Full Name", key="signup_fullname")
        st.text_input("Email", key="signup_email")
        st.text_input("Choose a Password", type="password", key="signup_pass")
        if st.button("Sign Up"):
            if add_user(st.session_state.signup_fullname, st.session_state.signup_email, st.session_state.signup_pass):
                st.success("Account created! Please proceed to login.")
                st.session_state.page = "login"
                st.rerun()
            else:
                st.error("This email is already registered.")
        st.markdown('</div>', unsafe_allow_html=True)

def home_page():
    st.title(f"Welcome to Your Dashboard, {st.session_state.get('fullname', '').split(' ')[0]}!")
    st.markdown("Your mission control for launching a successful career. Let's get started!")
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.header("🚀 Your Journey Begins Here")
        st.write("""
        This platform is designed to be your personal career co-pilot. We use powerful AI to help you understand your passions and turn them into a concrete plan for the future.
        """)
        st.info("**Your First Step:** Click on one of the tools below to begin your exploration!")
    with col2:
        image_path = "assets/main.jpg"
        try:
            st.image(image_path, width=600)
        except Exception:
            st.warning("`assets/main.jpg` not found. Please add it to your assets folder.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    st.header("Explore Your Tools")

    # This is a helper function to change pages via callbacks, the reliable way
    def set_page(page_name):
        st.session_state.page = page_name

    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container():
            st.markdown("""
            <div class="feature-card">
                <div class="feature-card-content">
                    <div class="icon">🤖</div>
                    <h3>Career Mentor</h3>
                    <p>Describe your interests and let our AI suggest personalized career paths for you.</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.button("Start Exploring", on_click=set_page, args=('mentor',), key="mentor_card", use_container_width=True)

    with c2:
        with st.container():
            st.markdown("""
            <div class="feature-card">
                <div class="feature-card-content">
                    <div class="icon">🗺️</div>
                    <h3>AI Roadmaps</h3>
                    <p>Get a custom, step-by-step roadmap for any field, from education to first job.</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.button("View Roadmaps", on_click=set_page, args=('roadmap',), key="roadmap_card", use_container_width=True)

    with c3:
        with st.container():
            st.markdown("""
            <div class="feature-card">
                <div class="feature-card-content">
                    <div class="icon">📄</div>
                    <h3>Jobs Placement</h3>
                    <p>Search for live job openings and find your place in the professional world.</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.button("Find Jobs", on_click=set_page, args=('jobs',), key="jobs_card", use_container_width=True)

def mentor_page():
    st.title("🤖 Career Mentor")
    st.markdown("Your personal AI assistant to guide you from interest to career.")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if 'stage' not in st.session_state: st.session_state.stage = 'get_interest'
    if st.session_state.stage == 'get_interest':
        st.header("🧠 What are you passionate about?")
        st.text_area("Tell me about your hobbies, favorite subjects, or what you dream of doing. The more detail, the better!", key="interest_text", height=150)
        if st.button("Find My Career Paths"):
            if st.session_state.interest_text:
                with st.spinner("AI is analyzing your interests..."):
                    st.session_state.suggested_fields = get_fields_from_gemini(st.session_state.interest_text)
                    st.session_state.interests = st.session_state.interest_text
                st.session_state.stage = 'select_field'
                st.rerun()
            else: st.warning("Please tell me about your interests first!")
    if st.session_state.stage == 'select_field':
        st.header("💡 Here are some career paths that match your interests:")
        if st.session_state.suggested_fields:
            chosen_field = st.radio("Which path would you like to explore in detail?", st.session_state.suggested_fields, key="field_choice")
            if st.button("Generate My Personal Plan"):
                st.session_state.chosen_field = chosen_field
                st.session_state.stage = 'show_plan'
                st.rerun()
        else:
            st.error("The AI could not determine career paths. Please try a different, more detailed interest.")
            if st.button("Try Again"):
                st.session_state.stage = 'get_interest'
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    if st.session_state.stage == 'show_plan':
        guidance_content = get_gemini_guidance(st.session_state.interests, st.session_state.chosen_field)
        if guidance_content:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(guidance_content)
            st.markdown('</div>', unsafe_allow_html=True)
        if st.button("⬅️ Explore Another Interest"):
            keys_to_clear = ['stage', 'chosen_field', 'suggested_fields', 'interests']
            for key in keys_to_clear:
                if key in st.session_state: del st.session_state[key]
            st.rerun()

def roadmap_page():
    st.title("🗺️ Career Roadmaps")
    st.markdown("A dynamic, AI-generated journey for your chosen career.")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if 'chosen_field' in st.session_state:
        st.info(f"Generating a custom roadmap for: **{st.session_state.chosen_field}**")
        roadmap_content = get_gemini_roadmap_interactive(st.session_state.chosen_field)
        if roadmap_content:
            parse_and_display_roadmap(roadmap_content)
        else:
            st.warning("Could not generate a roadmap at this time. Please try again.")
    else:
        st.warning("Please select a career in the '🤖 Career Mentor' page first to generate a personalized roadmap.")
    st.markdown('</div>', unsafe_allow_html=True)

def jobs_page():
    st.title("📄 Jobs Placement")
    st.markdown("Find live job opportunities related to your chosen field, anywhere in the world.")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        default_career = st.session_state.get('chosen_field', '')
        search_career = st.text_input("Enter a career or job title:", default_career, key="job_search_career")
    with col2:
        search_location = st.text_input("Enter a location (e.g., city, country):", "USA", key="job_search_location")
    if st.button("Search Jobs"):
        if not search_career:
            st.warning("Please enter a career or job title to search.")
        else:
            full_query = f"{search_career} in {search_location}"
            with st.spinner(f"Searching for '{full_query}'..."):
                st.session_state.jobs_df = get_real_world_jobs(full_query)
    if 'jobs_df' in st.session_state:
        jobs_df = st.session_state.jobs_df
        if jobs_df is not None and not jobs_df.empty:
            st.success(f"Found {len(jobs_df)} job postings!")
            st.dataframe(jobs_df, use_container_width=True, hide_index=True, column_config={"Link": st.column_config.LinkColumn("Apply", display_text="🔗 Apply")})
        elif jobs_df is not None:
            st.warning("Could not find any current job listings for this search. Try a broader location or career title.")
    st.markdown('</div>', unsafe_allow_html=True)

# --- UPDATED: Admin dashboard now shows ratings ---
def admin_dashboard_page():
    st.title("🔑 Admin Dashboard")
    st.markdown("View all registered users and submitted ratings.")

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.header("Registered Users")
    users_data = get_all_users()
    if users_data:
        df_users = pd.DataFrame(users_data, columns=['ID', 'Full Name', 'Email', 'Role'])
        st.dataframe(df_users, use_container_width=True, hide_index=True)
    else:
        st.info("No users have registered yet.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.header("User Ratings & Feedback")
    ratings_data = get_all_ratings()
    if ratings_data:
        df_ratings = pd.DataFrame(ratings_data, columns=['ID', 'Full Name', 'Email', 'Rating (out of 5)', 'Submitted At'])
        avg_rating = df_ratings['Rating (out of 5)'].mean()
        st.metric(label="Average App Rating", value=f"{avg_rating:.2f} ⭐")
        st.dataframe(df_ratings, use_container_width=True, hide_index=True)
    else:
        st.info("No ratings have been submitted yet.")
    st.markdown('</div>', unsafe_allow_html=True)


# --- Main Application Router ---
if not st.session_state.get('logged_in'):
    st.sidebar.title("Welcome!")
    selection = st.sidebar.radio("Get Started", ["Login", "Sign Up"])
    if selection == "Login": login_page()
    else: signup_page()
else:
    st.sidebar.title(f"Welcome, {st.session_state.get('fullname', '').split(' ')[0]}!")
    
    page_options = {"🏠 Home": "home", "🤖 Career Mentor": "mentor", "🗺️ Roadmap": "roadmap", "📄 Jobs Placement": "jobs"}
    if st.session_state.get('role') == 'admin':
        page_options["🔑 Admin Dashboard"] = "admin"
    
    if 'page' not in st.session_state:
        st.session_state.page = 'home'
    
    page_values = list(page_options.values())
    current_page_index = page_values.index(st.session_state.page) if st.session_state.page in page_values else 0
        
    page_selection = st.sidebar.radio("Navigation", list(page_options.keys()), index=current_page_index, key="sidebar_nav")
    
    if page_options[page_selection] != st.session_state.page:
        st.session_state.page = page_options[page_selection]
        st.rerun()

    # --- UPDATED: Sidebar now saves ratings correctly ---
    with st.sidebar:
        st.markdown('<div class="sidebar-bottom">', unsafe_allow_html=True)
        st.divider()
        st.subheader("Rate this App")
        rating = st.select_slider("How helpful was this app?", options=['⭐', '⭐⭐', '⭐⭐⭐', '⭐⭐⭐⭐', '⭐⭐⭐⭐⭐'], key="rating")
        
        if st.button("Submit Rating", key="rating_button", use_container_width=True):
            user_email = st.session_state.get('email')
            if user_email:
                add_rating(user_email, rating)
                st.sidebar.success("Thank you for your rating!")
                time.sleep(2)
                st.rerun() # To clear the success message after a delay
            else:
                st.sidebar.error("Error submitting rating.")

        st.divider()
        def logout():
            # Clear all session state keys to log out
            for key in list(st.session_state.keys()):
                del st.session_state[key]
        st.button("Logout", on_click=logout, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    page_map = {
        'home': home_page, 'mentor': mentor_page, 'roadmap': roadmap_page, 'jobs': jobs_page, 'admin': admin_dashboard_page
    }
    page_map[st.session_state.page]()

# --- Fixed Main Footer ---
st.markdown('<div class="main-footer">Career Mentor by Taha</div>', unsafe_allow_html=True)