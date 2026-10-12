import streamlit as st
import pandas as pd
import numpy as np
import datetime

# 1. إعدادات الصفحة
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 نظام التخطيط الهندسي الديناميكي - آكد")

# 2. رابط Google Sheets (يجب أن يكون Anyone with the link - Editor)
# قمنا بتحويل الرابط ليتم قراءته كملف CSV مباشر لتفادي تعقيدات المصادقة
SHEET_ID = "1RUqihUZreld3OY9M2cuPWtpxtuCS9p-2ut0FCFFwFvQ"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"

@st.cache_data(ttl=10) # تحديث البيانات كل 10 ثواني
def load_data():
    try:
        df = pd.read_csv(CSV_URL)
        # تنظيف وتجهيز التواريخ
        df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce').dt.date
        df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce').dt.date
        return df
    except Exception as e:
        return pd.DataFrame()

df_projects = load_data()

if df_projects.empty:
    st.error("⚠️ تعذر قراءة البيانات من Google Sheets. يرجى التأكد من أن الرابط متاح للعامة (Anyone with the link).")
    st.stop()

# 3. لوحة الإعدادات الجانبية (Capacity Settings)
st.sidebar.header("⚙️ إعدادات سعة الفرق")
st.sidebar.markdown("تحديد عدد المهندسين المتاحين حالياً:")

disciplines = ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"]
default_engineers = [16, 10, 5, 5, 12]
engineers = {}
capacities = {}
efficiency = st.sidebar.slider("معامل الكفاءة والإنتاجية (%)", 50, 100, 80) / 100.0

for disc, default in zip(disciplines, default_engineers):
    # مطابقة أسماء الأعمدة في الشيت
    col_name = f"{disc} (Hrs)" if disc != "Arch Tech" else "Arch Tech (Hrs)"
    engineers[disc] = st.sidebar.number_input(f"مهندسي {disc}", value=default, min_value=0)
    capacities[disc] = engineers[disc] * 40 * efficiency

# 4. واجهة إدخال البيانات (Table Editor)
st.subheader("📋 سجل المشاريع وتوزيع الساعات")
st.info("💡 لتحديث الساعات، يمكنك تعديل الجدول أدناه. (ملاحظة: في هذه النسخة المجانية المبسطة، التعديلات تتم برمجياً داخل التطبيق لتوليد التحليل، لحفظها نهائياً يفضل تحميلها كملف CSV أو إضافتها في الشيت مباشرة).")

# جدول قابل للتعديل
edited_df = st.data_editor(
    df_projects,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True
)

# 5. محرك الحسابات والخريطة الحرارية
st.markdown("---")
st.subheader("🔥 تحليل الاختناقات والسعة المتاحة (Heatmap)")

start_timeline = st.date_input("تاريخ بداية التحليل:", datetime.date(2026, 9, 20))
num_weeks = st.slider("عدد أسابيع التحليل:", 5, 20, 10)

weeks = [start_timeline + datetime.timedelta(days=7*i) for i in range(num_weeks)]
week_labels = [w.strftime("%d-%b") for w in weeks]

selected_disc = st.selectbox("اختر التخصص لعرض تفاصيله:", disciplines)
disc_col_name = f"{selected_disc} (Hrs)"

demand = [0] * num_weeks

# محرك الحساب عالي الدقة
for idx, row in edited_df.iterrows():
    if pd.isnull(row.get('Start Date')) or pd.isnull(row.get('End Date')) or pd.isnull(row.get(disc_col_name)):
        continue
        
    s_date = row['Start Date']
    e_date = row['End Date']
    total_hrs = float(row[disc_col_name])
    
    # حساب أيام العمل للمشروع (متجاهلاً الجمعة والسبت)
    workdays_total = np.busday_count(s_date, e_date + datetime.timedelta(days=1), weekmask='1111100')
    if workdays_total <= 0: continue
        
    daily_rate = total_hrs / workdays_total
    
    for i, w_start in enumerate(weeks):
        w_end = w_start + datetime.timedelta(days=6)
        overlap_start = max(s_date, w_start)
        overlap_end = min(e_date, w_end)
        
        if overlap_start <= overlap_end:
            overlap_days = np.busday_count(overlap_start, overlap_end + datetime.timedelta(days=1), weekmask='1111100')
            demand[i] += (daily_rate * overlap_days)

# 6. عرض النتيجة
results_df = pd.DataFrame({
    "المؤشر": ["الساعات المطلوبة (Demand)", "السعة المتاحة (Capacity)", "الفارق/الاختناق (Variance)"],
})

for i, w_label in enumerate(week_labels):
    dem = round(demand[i], 1)
    cap = capacities[selected_disc]
    var = round(cap - dem, 1)
    results_df[w_label] = [dem, cap, var]

def highlight_bottlenecks(val):
    if isinstance(val, (int, float)) and val < 0:
        return 'background-color: #ffcccc; color: #900000; font-weight: bold'
    return ''

st.dataframe(results_df.style.map(highlight_bottlenecks, subset=week_labels), use_container_width=True)

# زر لتحميل البيانات المعدلة
st.download_button(
    label="📥 تحميل البيانات كملف CSV",
    data=edited_df.to_csv(index=False).encode('utf-8'),
    file_name='Engineering_Resource_Updated.csv',
    mime='text/csv',
)
