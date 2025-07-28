#Install XGBoost and optuna
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier
from sentence_transformers import SentenceTransformer
from datetime import datetime
import optuna
import nltk

nltk.download('stopwords', quiet=True)

# --- Utility Functions ---
def preprocess_text(text):
    text = re.sub(r"[^A-Za-z]", " ", text.lower())
    tokens = text.split()
    tokens = [PorterStemmer().stem(word) for word in tokens if word not in stopwords.words('english')]
    return " ".join(tokens)

@st.cache_resource
def get_sentence_embeddings(texts):
    model = SentenceTransformer('all-MiniLM-L6-v2')
    return model.encode(texts, show_progress_bar=False)

def train_classifier(X, y):
    model = LogisticRegression(max_iter=200)
    model.fit(X, y)
    return model

def optimize_xgb(X, y):
    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 50, 200),
            "max_depth": trial.suggest_int("max_depth", 2, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3),
        }
        model = XGBClassifier(**params, use_label_encoder=False, eval_metric='mlogloss')
        model.fit(X, y)
        return model.score(X, y)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=10)
    return XGBClassifier(**study.best_params, use_label_encoder=False, eval_metric='mlogloss').fit(X, y)

def recommend_user(df):
    return df['assigned_to'].value_counts().idxmin()

def calculate_completion_rate(tasks):
    if not tasks:
        return 0
    completed = sum(1 for task in tasks if task["status"] == "Completed")
    return round((completed / len(tasks)) * 100, 2)

def task_dataframe():
    return pd.DataFrame(st.session_state.tasks)

# --- Streamlit App ---
st.set_page_config(page_title="Unified Task Manager", layout="wide")
st.title("Unified AI Task Management System")

# Initialize session state
if "tasks" not in st.session_state:
    st.session_state.tasks = []

# Sidebar Navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Add Task", "Tasks", "AI Insights"])

# Dashboard
if page == "Dashboard":
    st.header("Dashboard Overview")

    total_tasks = len(st.session_state.tasks)
    completed_tasks = sum(1 for task in st.session_state.tasks if task["status"] == "Completed")
    completion_rate = calculate_completion_rate(st.session_state.tasks)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Tasks", total_tasks)
    col2.metric("Completed Tasks", completed_tasks)
    col3.metric("Completion Rate", f"{completion_rate}%")

    df = task_dataframe()
    if not df.empty:
        fig1, ax1 = plt.subplots()
        df['category'].value_counts().plot.pie(autopct='%1.1f%%', ax=ax1)
        ax1.set_ylabel("")
        ax1.set_title("Task Distribution by Category")
        st.pyplot(fig1)

        fig2, ax2 = plt.subplots()
        df['priority'].value_counts().plot.pie(autopct='%1.1f%%', ax=ax2)
        ax2.set_ylabel("")
        ax2.set_title("Task Priority Distribution")
        st.pyplot(fig2)
    else:
        st.info("No task data available to display graphs.")

# Add Task
elif page == "Add Task":
    st.header("Add New Task")
    with st.form("add_task_form"):
        description = st.text_area("Task Description")
        estimated_hours = st.number_input("Estimated Hours", min_value=0.0, step=0.5)
        due_date = st.date_input("Due Date")
        category = st.text_input("Category")
        priority = st.selectbox("Priority", ["Low", "Medium", "High"])
        status = st.selectbox("Status", ["Pending", "In Progress", "Completed"])
        submitted = st.form_submit_button("Add Task")

        if submitted and description:
            new_task = {
                "description": description,
                "estimated_hours": estimated_hours,
                "due_date": str(due_date),
                "category": category,
                "priority": priority,
                "status": status
            }
            st.session_state.tasks.append(new_task)
            st.success("Task added successfully!")

# Task List
elif page == "Tasks":
    st.header("All Tasks")
    df = task_dataframe()
    if not df.empty:
        with st.expander("Filter Options"):
            status_filter = st.selectbox("Filter by Status", ["All"] + df['status'].unique().tolist())
            priority_filter = st.selectbox("Filter by Priority", ["All"] + df['priority'].unique().tolist())
            filtered_df = df.copy()
            if status_filter != "All":
                filtered_df = filtered_df[filtered_df['status'] == status_filter]
            if priority_filter != "All":
                filtered_df = filtered_df[filtered_df['priority'] == priority_filter]
        st.dataframe(filtered_df)
    else:
        st.info("No tasks available. Add some from the 'Add Task' section.")

# AI Insights
elif page == "AI Insights":
    st.header("AI-Based Task Priority Prediction")
    uploaded = st.file_uploader("Upload task dataset (CSV)", type=['csv'])
    if uploaded:
        df = pd.read_csv(uploaded)
        df.dropna(subset=['description', 'priority', 'assigned_to'], inplace=True)
        df['processed'] = df['description'].apply(preprocess_text)
        label_encoder = LabelEncoder()
        df['priority_encoded'] = label_encoder.fit_transform(df['priority'])
        df['user_encoded'] = LabelEncoder().fit_transform(df['assigned_to'])
        X = get_sentence_embeddings(df['description'].tolist())
        X_train, X_test, y_train, y_test = train_test_split(X, df['priority_encoded'], test_size=0.2, stratify=df['priority_encoded'], random_state=42)
        classifier = train_classifier(X_train, y_train)
        priority_model = optimize_xgb(X_train, y_train)

        y_pred = priority_model.predict(X_test)
        labels = list(range(len(label_encoder.classes_)))
        report = classification_report(y_test, y_pred, labels=labels, target_names=label_encoder.classes_, output_dict=True, zero_division=0)
        st.subheader("Classification Report")
        st.dataframe(pd.DataFrame(report).transpose())

        cm = confusion_matrix(y_test, y_pred, labels=labels)
        fig, ax = plt.subplots()
        ConfusionMatrixDisplay(cm, display_labels=label_encoder.classes_).plot(ax=ax)
        st.pyplot(fig)

        st.subheader("Enter a New Task for Prediction")
        desc = st.text_area("Task Description")
        if st.button("Predict Priority") and desc:
            vec = get_sentence_embeddings([desc])
            pred_priority = priority_model.predict(vec)[0]
            st.success(f"Predicted Priority: {label_encoder.inverse_transform([pred_priority])[0]}")
            st.info(f"Recommended User: {recommend_user(df)}")
