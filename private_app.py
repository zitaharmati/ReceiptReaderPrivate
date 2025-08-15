import streamlit as st
import base64
import json
import pandas as pd
import re
from groq import Groq, AuthenticationError
from io import StringIO, BytesIO
from azure.storage.blob import BlobClient
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
password = os.getenv("PASSWORD")
url_part=os.getenv("URL_PART")

def check_password():
    def password_entered():
        if st.session_state["password"] == password:
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password:", type="password", on_change=password_entered, key="password")
        st.error("Invalid password!")
        return False
    else:
        return True

def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=True, sheet_name='Sheet1')
    processed_data = output.getvalue()
    return processed_data

@st.cache_data(show_spinner="🔍 Blokk feldolgozása...", ttl=3600)
def process_receipt(image_bytes, api_key, expected_items):

    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    prompt_text = """Extract the following receipt details from the provided text response and return them as a structured JSON object. Return only JSON, no extra text or explanations

    Fields to extract:
    - Company
    - Date
    - Items (Description, Quantity, Unit Price, Total, Discounted total)
    - Deduction 
    - Total
    - Discounted Total
    - ProductType one of the following categories: food, alcoholic drink, paper product, toy, stationery, home decoration, DIY product, gardening, petrol, drugstore product, cloth, electric device, medicine, other. If not identified use "unknown".
    If the receipt contains discount try to extract the discounted price of the certain product as discounted total.
    The name of the product item is before the price of that item.
    """
    if expected_items > 0:
        prompt_text += f"""
    IMPORTANT: There are exactly {expected_items} items in the receipt. 
    Do not infer or hallucinate additional items. 
    Return exactly {expected_items} items in the 'Items' field of the JSON.
    """

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                        },
                    },
                ],
            }
        ],
        model="meta-llama/llama-4-scout-17b-16e-instruct",
    )

    result_str = response.choices[0].message.content
    match = re.search(r'\{.*\}', result_str, re.DOTALL)
    if not match:
        raise ValueError("No valid JSON found in model response.")

    result_json = json.loads(match.group(0))
    return result_json

if check_password():
    # --- UI ---
    st.title("🧾 Saját használatú blokk beolvasó appom")

    with st.sidebar:
        st.markdown("""
        <div style="background-color: #f8f0f5; padding: 15px; border-radius: 10px; border: 1px solid #e0cfe3;">
            <h4 style="color: #d6336c;">📘 Használati utasítás</h4>
            <ol style="padding-left: 20px; color: #333;">
                <li>📸 Készíts egy jó minőségű fotót a blokkról</li>
                <li>✂️ Vágd körbe megfelelően</li>
                <li>📤 Tölts fel a képet</li>
                <li>🔢 Ha az adatok beolvasása téves</li>
                    <ul style="padding-left: 20px; margin-top: 5px;">
                    <li>Töltsd fel még egyszer</li>
                    <li>Add meg a tételek pontos számát</li>
                    <li>Tölts fel egy másik képet</li>
                    </ul>
                <li>📥 Mentsd a táblákat a dropbox fiókba</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<p style="font-size:1.3rem; font-weight:bold;"></p>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:1.3rem; font-weight:bold;">📤 Fotó feltöltése</p>', unsafe_allow_html=True)

    image_file = st.file_uploader("Upload image", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
    st.markdown('<p style="font-size:1.3rem; font-weight:bold;"></p>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:1.3rem; font-weight:bold;">🔢 Blokkon szereplő tételek száma (amennyiben a beolvasás helytelen)</p>', unsafe_allow_html=True)

    expected_items = st.number_input("Blokkon szereplő tételek száma", min_value=0, step=1, label_visibility="collapsed")


    if image_file:
        st.image(image_file, caption="Feltöltött kép", use_container_width=True)

        fizeto = st.radio(
            "Ki fizette a számlát?",
            ("Zita", "Mátyás")
        )

        try:
            image_bytes = image_file.read()
            result_json = process_receipt(image_bytes, api_key, expected_items)

            items_df = pd.DataFrame(result_json["Items"])
            total_without_discount = items_df["Total"].sum()
            summary_df = pd.DataFrame([{
                "Company": result_json.get("Company", "Unknown"),
                "Date": result_json.get("Date", "Unknown"),
                "Discount" : result_json.get("Deduction", 0),
                "Total": result_json.get("Total", "Unknown"),
                
            }])
                       
            # Display and download logic remains unchanged
            st.subheader("📋 Summary")
            st.dataframe(summary_df)
            summary_df["Paid_by"] = fizeto
            date = summary_df["Date"].values
            company = summary_df["Company"].values

            if st.button("Összesítő mentése tárhelyre"):
                try:
                    blob_url = fr"https://mystorageforexcelfiles.blob.core.windows.net/demo/summary_{company}{date}.xlsx?{url_part}"
                    blob_client = BlobClient.from_blob_url(blob_url)
                    data=convert_df_to_excel(summary_df)
                    blob_client.upload_blob(data, overwrite=True)
                    st.success(f"Sikeres mentés")
                except Exception as e:
                    st.error(f"Hiba történt: {e}")

            st.download_button(
                label="Összesítő letöltése excelben",
                data=convert_df_to_excel(summary_df),
                file_name='osszesito.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

            st.subheader("🛒 Items")
            st.dataframe(items_df)
            
            try:
                if summary_df["Discount"].values == 0:
                    grouped = items_df.groupby("ProductType")["Total"].sum().reset_index()
                    st.subheader("📊 Termékkategóriák szerinti bontás")
                    st.dataframe(grouped)
                    st.bar_chart(grouped.set_index("ProductType"))
                else:
                    grouped = items_df.groupby("ProductType")["Discounted Total"].sum().reset_index()
                    st.subheader("📊 Termékkategóriák szerinti bontás")
                    st.dataframe(grouped)
                    st.bar_chart(grouped.set_index("ProductType"))

            except Exception:
                st.warning("⚠️ Termékkategória felismerése sikertelen volt")

            if st.button("Részletező mentése tárhelyre"):
                try:
                    blob_url = fr"https://mystorageforexcelfiles.blob.core.windows.net/demo/items_{company}{date}.xlsx?{url_part}"
                    blob_client = BlobClient.from_blob_url(blob_url)
                    data=convert_df_to_excel(items_df)
                    blob_client.upload_blob(data, overwrite=True)
                    st.success(f"Sikeres mentés")
                except Exception as e:
                    st.error(f"Hiba történt: {e}")
               
            st.download_button(
                label="Részletező letöltése excelben",
                data=convert_df_to_excel(items_df),
                file_name='items.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        except AuthenticationError:
            st.error("🚫 Invalid API key. Please check your Groq key and try again.")
            st.stop()
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            st.error("🚫 Receipt processing failed. Please upload a clearer image.")

