import pandas as pd
import numpy as np
import requests
import json
import streamlit as st
from PIL import Image
import os
from dotenv import load_dotenv
import re
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables
load_dotenv()

# Initialize Firestore
firebase_key = os.getenv("FIREBASE_CREDENTIALS_JSON")
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(firebase_key))
    firebase_admin.initialize_app(cred)

# Initialize Firestore DB
db = firestore.client()

# Initialize Streamlit App
st.set_page_config(page_title="MLB StatShot App")
st.header("MLB StatShot ⚾")

# Set global options
pd.set_option('display.max_colwidth', 200)

# Configure Google Generative AI
import google.generativeai as genai
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Function to Load Newline Delimited JSON into Pandas DataFrame
def load_newline_delimited_json(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = [json.loads(line) for line in response.text.strip().split('\n')]
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error loading JSON: {e}")
        return None

# Function to Process Results from MLB Stats API Endpoints
def process_endpoint_url(endpoint_url, pop_key=None):
    try:
        response = requests.get(endpoint_url)
        response.raise_for_status()
        data = json.loads(response.content)
        if pop_key:
            df_result = pd.json_normalize(data.pop(pop_key), sep="_")
        else:
            df_result = pd.json_normalize(data)
        return df_result
    except Exception as e:
        st.error(f"Error processing endpoint: {e}")
        return None

# Function to Get All Players for a Given Season
def get_all_players(season):
    url = f'https://statsapi.mlb.com/api/v1/sports/1/players?season=2024'
    return process_endpoint_url(url, 'people')

# Function to Search for a Player by Name
def search_player_by_name(players_df, player_name):
    if players_df is None or players_df.empty:
        return None, "Players list is empty or unavailable."
    try:
        escaped_name = re.escape(player_name.strip())
        player_row = players_df[players_df['fullName'].str.contains(escaped_name, case=False, na=False)]
        if player_row.empty:
            return None, f"No player found with the name '{player_name}'."
        player_id = player_row.iloc[0]['id']
        return player_id, None
    except Exception as e:
        return None, f"Error during player search: {e}"

# Function to Get Player Details by ID
def get_player_details(player_id):
    url = f'https://statsapi.mlb.com/api/v1/people/{player_id}/'
    try:
        response = requests.get(url)
        response.raise_for_status()
        return json.loads(response.content)
    except Exception as e:
        st.error(f"Error fetching player details: {e}")
        return None

# Function to Setup Image Input
def input_image_setup(uploaded_file):
    if uploaded_file is not None:
        bytes_data = uploaded_file.getvalue()
        image_parts = [{"mime_type": uploaded_file.type, "data": bytes_data}]
        return image_parts
    else:
        raise FileNotFoundError("No file uploaded")

# Function to Get Player Name from Image Using Gemini
def get_player_name_from_image(input_prompt, image):
    try:
        model = genai.GenerativeModel('gemini-1.5-pro')
        response = model.generate_content([input_prompt, image[0]])
        return response.text.strip()  # Clean response
    except Exception as e:
        st.error(f"Error generating Gemini response: {e}")
        return None

# Function to Save User Data to Firestore
def save_user_data(email, player_name, language):
    try:
        user_ref = db.collection('users').add({
            'email': email,
            'player_name': player_name,
            'language': language
        })
        st.success(f"Data saved for {player_name}.")
    except Exception as e:
        st.error(f"Error saving user data: {e}")

# Function to get player stats
def get_player_stats(player_id, season):
    """
    Fetches player stats for a given season.

    Args:
        player_id (int): The player's ID.
        season (int): The MLB season year.

    Returns:
        list: A list of stat groups for the player (e.g., hitting, pitching, fielding).
    """
    try:
        # Call the same API with the "stats" hydrate
        response = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}",
            params={
                "season": season,
                "hydrate": f"stats(group=[hitting],type=season,season={season})",
            },
        )
        if response.status_code == 200:
            data = response.json()
            stats = data.get("people", [{}])[0].get("stats", [])
            return stats
        else:
            st.error(f"Error fetching stats: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"An unexpected error occurred while fetching player stats: {e}")
        return None
        

# Application Logic
uploaded_file = st.file_uploader("Upload an image of a current MLB player. Use an image with the player's jersey and number for best results. 📸", type=["jpg", "jpeg", "png"])
image = None

# Language selection dropdown for summary and DataFrame
language_options = {
    "English 🇺🇸": "English",
    "Spanish 🇪🇸": "Spanish",
    "Japanese 🇯🇵": "Japanese",
    "French 🇫🇷": "French",
    "Chinese 🇨🇳": "Chinese"
}

# Select language (the user sees the emojis, but the variable stores the text)
language_display = st.selectbox("Select Language", list(language_options.keys()), index=0)

# Get the selected language text without the emoji
language = language_options[language_display]

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Image.", use_container_width=True)  # Ensure image is shown

    # Display email input below the image
    email = st.text_input("Enter your email 📧")

    # Analyze button below the email input
    submit = st.button("Analyze Image ✅")

    # Validate that email is entered before allowing image analysis
    if submit:
        if not email:
            st.error("Please enter your email before analyzing the image.")
        else:
            try:
                # Get player name from image based on fixed input prompt (no language here)
                input_prompt = """
                You are an expert in baseball strategy and MLB players.
                If the user uploads an image of a specific player, write the player's first and last name. For example, if the player is Aaron Judge, write "Aaron Judge".
                """
                image_data = input_image_setup(uploaded_file)
                gemini_response = get_player_name_from_image(input_prompt, image_data)
                st.write(f"Extracted Player Name: {gemini_response}")

                # Validate response
                if not gemini_response:
                    st.error("Could not extract player name from the image.")
                    st.stop()

                # Save user data to Firestore, including language
                save_user_data(email, gemini_response, language)

                # Get all players for the 2024 season
                season = 2024
                players_df = get_all_players(season)

                if players_df is None or players_df.empty:
                    st.error("Could not fetch players for the 2024 season.")
                    st.stop()

                # Search for the player by name
                player_id, error_message = search_player_by_name(players_df, gemini_response)
                if error_message:
                    st.error(error_message)
                    st.stop()

                # Fetch player details
                player_details = get_player_details(player_id)
                
                if player_details and "people" in player_details:
                    # Extract the first player's information
                    player_info = player_details["people"][0]
                
                    # Language translations for the key attributes

                    # Updated translations dictionary to include Chinese
                    translations = {
                        "Full Name": {
                            "English": "Full Name",
                            "Spanish": "Nombre Completo",
                            "Japanese": "フルネーム",
                            "French": "Nom Complet",
                            "Chinese": "全名"
                        },
                        "Primary Position": {
                            "English": "Primary Position",
                            "Spanish": "Posición Principal",
                            "Japanese": "主なポジション",
                            "French": "Position Principale",
                            "Chinese": "主要位置"
                        },
                        "Jersey Number": {
                            "English": "Jersey Number",
                            "Spanish": "Número de Camisa",
                            "Japanese": "ジャージ番号",
                            "French": "Numéro de Maillot",
                            "Chinese": "球衣号码"
                        },
                        "Birth Date": {
                            "English": "Birth Date",
                            "Spanish": "Fecha de Nacimiento",
                            "Japanese": "生年月日",
                            "French": "Date de Naissance",
                            "Chinese": "出生日期"
                        },
                        "Current Age": {
                            "English": "Current Age",
                            "Spanish": "Edad Actual",
                            "Japanese": "現在の年齢",
                            "French": "Âge Actuel",
                            "Chinese": "当前年龄"
                        },
                        "Birthplace": {
                            "English": "Birthplace",
                            "Spanish": "Lugar de Nacimiento",
                            "Japanese": "出生地",
                            "French": "Lieu de Naissance",
                            "Chinese": "出生地"
                        },
                        "Height": {
                            "English": "Height",
                            "Spanish": "Altura",
                            "Japanese": "身長",
                            "French": "Taille",
                            "Chinese": "身高"
                        },
                        "Weight (lbs)": {
                            "English": "Weight (lbs)",
                            "Spanish": "Peso (lbs)",
                            "Japanese": "体重 (ポンド)",
                            "French": "Poids (lbs)",
                            "Chinese": "体重 (磅)"
                        },
                        "Active Player": {
                            "English": "Active Player",
                            "Spanish": "Jugador Activo",
                            "Japanese": "現役選手",
                            "French": "Joueur Actif",
                            "Chinese": "现役球员"
                        },
                        "MLB Debut Date": {
                            "English": "MLB Debut Date",
                            "Spanish": "Fecha del Debut en MLB",
                            "Japanese": "MLB デビュー日",
                            "French": "Date des Débuts en MLB",
                            "Chinese": "MLB 首秀日期"
                        },
                        "Bats": {
                            "English": "Bats",
                            "Spanish": "Batea",
                            "Japanese": "打撃",
                            "French": "Bats",
                            "Chinese": "打击"
                        },
                        "Throws": {
                            "English": "Throws",
                            "Spanish": "Lanza",
                            "Japanese": "投げる",
                            "French": "Lance",
                            "Chinese": "投掷"
                        },
                        "Nickname": {
                            "English": "Nickname",
                            "Spanish": "Apodo",
                            "Japanese": "ニックネーム",
                            "French": "Surnom",
                            "Chinese": "昵称"
                        }
                    }
                    
                    # Function to get the translated attribute name based on the selected language
                    def translate_attribute(attribute_name, language):
                        return translations.get(attribute_name, {}).get(language, attribute_name)
                    
                    # Displaying the player details table in the selected language
                    key_attributes = {
                        "Full Name": player_info.get("fullName", "N/A"),
                        "Primary Position": player_info.get("primaryPosition", {}).get("name", "N/A"),
                        "Jersey Number": player_info.get("primaryNumber", "N/A"),
                        "Birth Date": player_info.get("birthDate", "N/A"),
                        "Current Age": player_info.get("currentAge", "N/A"),
                        "Birthplace": f"{player_info.get('birthCity', 'N/A')}, {player_info.get('birthStateProvince', 'N/A')}, {player_info.get('birthCountry', 'N/A')}",
                        "Height": player_info.get("height", "N/A"),
                        "Weight (lbs)": player_info.get("weight", "N/A"),
                        "Active Player": "Yes" if player_info.get("active") else "No",
                        "MLB Debut Date": player_info.get("mlbDebutDate", "N/A"),
                        "Bats": player_info.get("batSide", {}).get("description", "N/A"),
                        "Throws": player_info.get("pitchHand", {}).get("description", "N/A"),
                        "Nickname": player_info.get("nickName", "N/A"),
                    }
                    
                    # Translate key attributes to the selected language
                    translated_attributes = {translate_attribute(k, language): v for k, v in key_attributes.items()}
                    
                    # Convert the translated attributes to a DataFrame
                    details_df = pd.DataFrame(list(translated_attributes.items()), columns=["Attribute", "Value"])
                    st.table(details_df)
                    
                    # Generate a textual summary with key attributes based on the selected language
                    if language == "Spanish":
                        summary = f"""
                        **{key_attributes['Full Name']}**, conocido como "{key_attributes['Nickname']}", es un {key_attributes['Primary Position']} 
                        que usa el número de camiseta **{key_attributes['Jersey Number']}**. Nació el **{key_attributes['Birth Date']}** en 
                        **{key_attributes['Birthplace']}**, y actualmente tiene **{key_attributes['Current Age']} años**.
                    
                        Mide **{key_attributes['Height']}** y pesa **{key_attributes['Weight (lbs)']} lbs**, batea como **{key_attributes['Bats']}** 
                        y lanza como **{key_attributes['Throws']}**. Este jugador hizo su debut en MLB el **{key_attributes['MLB Debut Date']}** 
                        y actualmente está **activo** en la liga.
                        """
                    elif language == "Japanese":
                        summary = f"""
                        **{key_attributes['Full Name']}**、ニックネームは"{key_attributes['Nickname']}"、ポジションは{key_attributes['Primary Position']}で 
                        背番号は**{key_attributes['Jersey Number']}**です。**{key_attributes['Birth Date']}**に生まれ、 
                        **{key_attributes['Birthplace']}**出身で、現在の年齢は**{key_attributes['Current Age']}歳**です。
                    
                        身長は**{key_attributes['Height']}**、体重は**{key_attributes['Weight (lbs)']} lbs**、打席は**{key_attributes['Bats']}** 
                        、投げる手は**{key_attributes['Throws']}**です。この選手は**{key_attributes['MLB Debut Date']}**にメジャーデビューし、現在 
                        {"現役" if key_attributes['Active Player'] == "Yes" else "引退"}しています。
                        """
                    elif language == "French":
                        summary = f"""
                        **{key_attributes['Full Name']}**, surnommé "{key_attributes['Nickname']}", est un joueur de {key_attributes['Primary Position']} 
                        avec le numéro de maillot **{key_attributes['Jersey Number']}**. Né le **{key_attributes['Birth Date']}** à 
                        **{key_attributes['Birthplace']}**, il a actuellement **{key_attributes['Current Age']} ans**.
                    
                        Il mesure **{key_attributes['Height']}** et pèse **{key_attributes['Weight (lbs)']} lbs**, il frappe en **{key_attributes['Bats']}** 
                        et lance avec **{key_attributes['Throws']}**. Ce joueur a fait ses débuts en MLB le **{key_attributes['MLB Debut Date']}** 
                        et il est actuellement {"actif" if key_attributes['Active Player'] == "Yes" else "inactif"} dans la ligue.
                        """
                    elif language == "Chinese":
                        summary = f"""
                        **{key_attributes['Full Name']}**，昵称为“{key_attributes['Nickname']}”，是一名 **{key_attributes['Primary Position']}** 球员，
                        背号为 **{key_attributes['Jersey Number']}**。他于 **{key_attributes['Birth Date']}** 出生在 **{key_attributes['Birthplace']}**，
                        现年 **{key_attributes['Current Age']} 岁**。
                    
                        他身高 **{key_attributes['Height']}**，体重 **{key_attributes['Weight (lbs)']} 磅**，打击习惯为 **{key_attributes['Bats']}**，
                        投球习惯为 **{key_attributes['Throws']}**。这位球员在 **{key_attributes['MLB Debut Date']}** 完成了他的 MLB 首秀，
                        他目前在联盟中是 **{"活跃" if key_attributes['Active Player'] == "Yes" else "非活跃"}** 状态。
                        """
                    else:
                        summary = f"""
                        **{key_attributes['Full Name']}**, also known as "{key_attributes['Nickname']}", is a {key_attributes['Primary Position']} 
                        wearing jersey number **{key_attributes['Jersey Number']}**. Born on **{key_attributes['Birth Date']}** in 
                        **{key_attributes['Birthplace']}**, they are currently **{key_attributes['Current Age']} years old**.
                    
                        Standing at **{key_attributes['Height']}** and weighing **{key_attributes['Weight (lbs)']} lbs**, they bat **{key_attributes['Bats']}** 
                        and throw **{key_attributes['Throws']}**. This player made their MLB debut on **{key_attributes['MLB Debut Date']}** 
                        and is currently **{key_attributes['Active Player']}** in the league.
                        """
                    
                    # Display the generated summary based on the language
                    st.markdown(summary)



                    # Fetch player stats for the most recent season
                    player_stats = get_player_stats(player_id, season)
            
                                
                    # Translation dictionary for stats in multiple languages
                    translations_stats = {
                        "Team": {"Spanish": "Equipo", "Japanese": "チーム", "French": "Équipe", "Chinese": "球队"},
                        "Player": {"Spanish": "Jugador", "Japanese": "選手", "French": "Joueur", "Chinese": "球员"},
                        "League": {"Spanish": "Liga", "Japanese": "リーグ", "French": "Ligue", "Chinese": "联赛"},
                        "Sport": {"Spanish": "Deporte", "Japanese": "スポーツ", "French": "Sport", "Chinese": "体育"},
                        "Games Played": {"Spanish": "Juegos Jugados", "Japanese": "試合数", "French": "Matchs joués", "Chinese": "比赛场次"},
                        "Ground Outs": {"Spanish": "Eliminaciones en Tierra", "Japanese": "ゴロアウト", "French": "Retirés au sol", "Chinese": "滚地出局"},
                        "Air Outs": {"Spanish": "Eliminaciones por Aire", "Japanese": "フライアウト", "French": "Retirés en l'air", "Chinese": "飞球出局"},
                        "Runs": {"Spanish": "Carreras", "Japanese": "得点", "French": "Points", "Chinese": "得分"},
                        "Doubles": {"Spanish": "Dobles", "Japanese": "二塁打", "French": "Doubles", "Chinese": "二垒打"},
                        "Triples": {"Spanish": "Triples", "Japanese": "三塁打", "French": "Triples", "Chinese": "三垒打"},
                        "Home Runs": {"Spanish": "Jonrones", "Japanese": "本塁打", "French": "Circuits", "Chinese": "本垒打"},
                        "Strike Outs": {"Spanish": "Ponches", "Japanese": "三振", "French": "Retirés sur des prises", "Chinese": "三振出局"},
                        "Base On Balls": {"Spanish": "Bases por Bolas", "Japanese": "四球", "French": "But sur balles", "Chinese": "四坏球"},
                        "Hits": {"Spanish": "Hits", "Japanese": "安打", "French": "Coups sûrs", "Chinese": "安打"},
                        "At Bats": {"Spanish": "Turnos al Bate", "Japanese": "打数", "French": "Présences au bâton", "Chinese": "打席"},
                        "Stolen Bases": {"Spanish": "Bases Robadas", "Japanese": "盗塁", "French": "But volé", "Chinese": "盗垒"},
                        "RBI": {"Spanish": "Carreras Impulsadas", "Japanese": "打点", "French": "Points produits", "Chinese": "打点"}
                        # Add additional translations for other stats as needed
                    }
                    
                    # Function to get the translated stat name
                    def get_translated_stat(stat_name, selected_lang):
                        return translations_stats.get(stat_name, {}).get(selected_lang, stat_name)
                    
                    # If player stats are available
                    if player_stats:
                        for stat_group in player_stats:
                            group_name = str(stat_group.get('group', 'N/A')).capitalize()
                            stats_type = str(stat_group.get('type', 'N/A')).capitalize()
                    
                            # Display the title with player name and season
                            st.write(f"**{key_attributes['Full Name']}** - {season} Season Stats:")
                    
                            stats_splits = stat_group.get('splits', [])
                    
                            # If there are splits (stat categories) available, process them
                            if stats_splits:
                                cleaned_data = []
                                for split in stats_splits:
                                    # Flatten the stats data and add relevant fields
                                    flattened_split = {
                                        "Team": split.get("team", {}).get("name", "N/A"),
                                        "Player": split.get("player", {}).get("fullName", "N/A"),
                                        "Games Played": split.get("stat", {}).get("gamesPlayed", "N/A"),
                                        "Runs": split.get("stat", {}).get("runs", "N/A"),
                                        "Hits": split.get("stat", {}).get("hits", "N/A"),
                                        "Home Runs": split.get("stat", {}).get("homeRuns", "N/A"),
                                        "Stolen Bases": split.get("stat", {}).get("stolenBases", "N/A"),
                                        "RBI": split.get("stat", {}).get("rbi", "N/A")
                                    }
                                    cleaned_data.append(flattened_split)
                    
                                    # Create a DataFrame from the cleaned data
                                    stats_df = pd.DataFrame(cleaned_data)
                                    
                                    # Remove the 'Player' column if it exists
                                    if "Player" in stats_df.columns:
                                        stats_df = stats_df.drop(columns=["Player"])
                                    
                                    # Convert the DataFrame into the two-column format (Stat, Value)
                                    if not stats_df.empty:
                                        # Melt the DataFrame into a two-column format
                                        stats_df_two_columns = pd.melt(stats_df, var_name="Stat", value_name="Value")
                                        
                                        # Translate the column names based on the selected language (if applicable)
                                        stats_df_two_columns['Stat'] = stats_df_two_columns['Stat'].apply(lambda x: get_translated_stat(x, language))
                                    
                                        # Translate the 'Value' column name
                                        stats_df_two_columns = stats_df_two_columns.rename(columns={"Stat": get_translated_stat("Stat", language), "Value": get_translated_stat("Value", language)})
                                        
                                        # Display the translated two-column stats table
                                        st.dataframe(stats_df_two_columns)
                                    else:
                                        st.write("No data available for this group.")
                                                                                                    

    
            except Exception as e:
                st.error(f"Error during analysis: {e}")



def save_feedback_to_database(email, feedback, email_updates, language):
    """
    Save the user's feedback to the database.
    
    Parameters:
        email (str): The user's email address.
        feedback (str): The feedback ("Yes" or "No").
    """

    # Reference to the feedback collection
    feedback_ref = db.collection("user_feedback")

    # Create a document for the feedback
    feedback_data = {
        "email": email,
        "feedback": feedback,
        "email_updates": email_updates,
        "language": language,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    
    # Add the feedback to the collection
    feedback_ref.add(feedback_data)

# Feedback section at the end of the app
st.write("### Feedback")

# Collect feedback from the user: "Yes" or "No"
feedback = st.radio("Was the image analysis accurate?", options=["Yes", "No"])

# Ask the user if they agree to receive email updates
email_updates = st.radio("Would you like to receive email updates?", options=["Yes", "No"])

# Button to submit feedback
feedback_submit = st.button("Submit Feedback")

# Save the feedback to the database when the button is clicked
if feedback_submit:
    if not email:
        st.error("Please enter your email earlier to save your feedback.")
    else:
        try:
            # Call a function to save feedback to the database along with the email update preference
            save_feedback_to_database(email, feedback, email_updates, language)
            st.success("Thank you for your feedback! It has been saved.")
        except Exception as e:
            st.error(f"An error occurred while saving your feedback: {e}")
