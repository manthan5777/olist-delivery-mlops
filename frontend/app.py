import os

import requests
import streamlit as st


API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://localhost:8001",
).rstrip("/")


st.set_page_config(
    page_title="Olist Delivery Predictor",
    page_icon="📦",
    layout="wide",
)

st.title("📦 Olist Delivery Predictor")

st.write(
    "Predict delivery risk and run background processing jobs."
)

st.caption(f"Configured API address: {API_BASE_URL}")


# --------------------------------------------------
# API HEALTH
# --------------------------------------------------

st.subheader("System health")

if st.button("Check API connection"):
    try:
        response = requests.get(
            f"{API_BASE_URL}/health",
            timeout=5,
        )

        response.raise_for_status()

        st.success("FastAPI connection successful.")
        st.json(response.json())

    except requests.RequestException as error:
        st.error("Could not connect to FastAPI.")
        st.exception(error)


# --------------------------------------------------
# BACKGROUND JOB
# --------------------------------------------------

st.divider()

st.subheader("Background job demonstration")

st.write(
    "This sends a job from Streamlit to FastAPI. "
    "FastAPI places it in Redis, and the worker processes it."
)

if "job_id" not in st.session_state:
    st.session_state.job_id = None


if st.button("Start background job"):
    try:
        response = requests.post(
            f"{API_BASE_URL}/jobs/demo",
            timeout=5,
        )

        response.raise_for_status()

        job_data = response.json()

        st.session_state.job_id = job_data["job_id"]

        st.success("Background job accepted.")

        st.write(f"Job ID: `{job_data['job_id']}`")
        st.write(f"Initial status: `{job_data['status']}`")

    except requests.RequestException as error:
        st.error("Could not create the background job.")
        st.exception(error)


if st.session_state.job_id:
    st.write(
        f"Current job ID: `{st.session_state.job_id}`"
    )

    if st.button("Check job status"):
        try:
            response = requests.get(
                (
                    f"{API_BASE_URL}/jobs/"
                    f"{st.session_state.job_id}"
                ),
                timeout=5,
            )

            response.raise_for_status()

            job_status = response.json()

            status_value = job_status.get(
                "status",
                "unknown",
            )

            if status_value == "completed":
                st.success("Background job completed.")

            elif status_value == "failed":
                st.error("Background job failed.")

            elif status_value == "processing":
                st.info("Worker is processing the job.")

            else:
                st.warning(
                    f"Current status: {status_value}"
                )

            st.json(job_status)

        except requests.RequestException as error:
            st.error("Could not retrieve job status.")
            st.exception(error)