import streamlit as st
import os
from datetime import datetime
from groupme_cal import generate_calendar  # Import your existing logic

# Load environment variables
GROUPME_TOKEN = os.getenv("GROUPME_TOKEN", "")
DEFAULT_GROUP_IDS = os.getenv("GROUPME_GROUP_IDS", "")

# Streamlit UI
st.set_page_config(page_title="GroupMe → ICS Calendar Feed", layout="centered")
st.title("📅 GroupMe → ICS Calendar Feed")

# Section: Manage GroupMe IDs
st.subheader("Manage GroupMe Group IDs")
group_ids_input = st.text_area(
    "Enter GroupMe Group IDs (comma-separated):",
    DEFAULT_GROUP_IDS,
    help="These IDs will be used to fetch events from GroupMe."
)

# Button to save IDs (for persistence, you'd update env vars or config file)
if st.button("Save IDs"):
    st.success("Group IDs updated! (Update environment variables or push changes for persistence)")

# Section: Generate ICS
st.subheader("Generate Calendar Feed")
if st.button("Generate ICS"):
    # Parse IDs
    group_ids = [gid.strip() for gid in group_ids_input.split(",") if gid.strip()]

    if not GROUPME_TOKEN:
        st.error("Missing GROUPME_TOKEN environment variable!")
    elif not group_ids:
        st.error("Please enter at least one GroupMe Group ID.")
    else:
        try:
            # Call your existing function to generate ICS content
            ics_content = generate_calendar(GROUPME_TOKEN, group_ids)

            # Save ICS file
            ics_path = "/tmp/calendar.ics"
            with open(ics_path, "w") as f:
                f.write(ics_content)

            # Provide download button
            st.success("ICS file generated successfully!")
            st.download_button(
                label="Download ICS",
                data=open(ics_path, "rb"),
                file_name="calendar.ics",
                mime="text/calendar"
            )

            st.info("For live subscription, deploy this app and use its public URL with `/calendar.ics` endpoint.")
        except Exception as e:
            st.error(f"Error generating calendar: {e}")