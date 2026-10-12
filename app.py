import streamlit as st
import pandas as pd
import numpy as np
import datetime
from streamlit_gsheets import GSheetsConnection

# 1. إعدادات الصفحة
st.set_page_config(page_title="Engineering Resource Planner", layout="wide")
st.title("📊 نظام التخطيط الهندسية الديناميكي - آكد")

# 2. الاتصال بقاعدة بيانات Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

# اسم ورقة العمل التي أنشأناها
SHEET_NAME = "Database"

@st.cache_data(ttl=5) # تحديث الكاش كل 5 ثواني
def fetch_data():
    return conn.read(worksheet=SHEET_NAME, usecols=list(range(9)))

# 3. جلب البيانات
try:
    df_projects = fetch_data()
    # تأكد من تحويل التواريخ إلى صيغة Date object
    df_projects['Start Date'] = pd.to_datetime(df_projects['Start Date']).dt.date
    df_projects['End Date'] = pd.to_datetime(df_projects['End Date']).dt.date
except Exception as e:
    st.error("لم يتم العثور على قاعدة البيانات. يرجى التأكد من ربط Google Sheets.")
    st.stop()

# 4. لوحة الإعدادات الجانبية (Capacity Settings)
st.sidebar.header("⚙️ إعدادات سعة الفرق")
st.sidebar.markdown("تحديد عدد المهندسين المتاحين حالياً:")

disciplines = ["Arch Tech", "Structural", "Plumbing", "HVAC", "Electrical"]
default_engineers = [16, 10, 5, 5, 12]

engineers = {}
capacities = {}
efficiency = st.sidebar.slider("معامل الكفاءة والإنتاجية (%)", 50, 100, 80) / 100.0

for disc, default in zip(disciplines, default_engineers):
    engineers[disc] = st.sidebar.number_input(f"مهندسي {disc}", value=default, min_value=0)
    capacities[disc] = engineers[disc] * 40 * efficiency

# 5. واجهة إدخال البيانات (Table Editor) - الحفظ التلقائي
st.subheader("📋 سجل المشاريع وتوزيع الساعات (تحديث تلقائي)")
st.info("أي تعديل تجريه هنا سيتم حفظه تلقائياً في Google Sheets المربوطة والمشتركة مع الإدارة.")

# جدول قابل للتعديل والإضافة (Dynamic)
edited_df = st.data_editor(
    df_projects,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True
)

# التحقق من وجود تعديلات ليتم الحفظ (Auto-save trigger)
if not edited_df.equals(df_projects):
    # حفظ البيانات في Google Sheets
    conn.update(worksheet=SHEET_NAME, data=edited_df)
    st.success("✅ تم تحديث قاعدة البيانات السحابية بنجاح!")
    st.cache_data.clear() # تفريغ الكاش لإعادة القراءة

# 6. محرك الحسابات والخريطة الحرارية (Engine & Heatmap)
st.markdown("---")
st.subheader("🔥 تحليل الاختناقات والسعة المتاحة (Heatmap)")

start_timeline = st.date_input("تاريخ بداية التحليل:", datetime.date(2026, 9, 20))
num_weeks = st.slider("عدد أسابيع التحليل:", 5, 20, 10)

weeks = [start_timeline + datetime.timedelta(days=7*i) for i in range(num_weeks)]
week_labels = [w.strftime("%d-%b") for w in weeks]

# اختيار التخصص لعرض خريطته
selected_disc = st.selectbox("اختر التخصص لعرض تفاصيله:", disciplines)
disc_col_name = f"{selected_disc} (Hrs)"

demand = [0] * num_weeks

# محرك الحساب عالي الدقة (أيام العمل الفعلية) - يحاكي إكسيل
for idx, row in edited_df.iterrows():
    if pd.isnull(row['Start Date']) or pd.isnull(row['End Date']) or pd.isnull(row[disc_col_name]):
        continue
        
    s_date = row['Start Date']
    e_date = row['End Date']
    total_hrs = row[disc_col_name]
    
    # حساب أيام العمل للمشروع (بايثون numpy - 5 هو الجمعة و 6 هو السبت)
    workdays_total = np.busday_count(s_date, e_date + datetime.timedelta(days=1), weekmask='1111100')
    if workdays_total <= 0: continue
        
    daily_rate = total_hrs / workdays_total
    
    for i, w_start in enumerate(weeks):
        w_end = w_start + datetime.timedelta(days=6)
        
        # التقاطع
        overlap_start = max(s_date, w_start)
        overlap_end = min(e_date, w_end)
        
        if overlap_start <= overlap_end:
            overlap_days = np.busday_count(overlap_start, overlap_end + datetime.timedelta(days=1), weekmask='1111100')
            demand[i] += (daily_rate * overlap_days)

# عرض النتيجة
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

st.dataframe(results_df.style.applymap(highlight_bottlenecks, subset=week_labels), use_container_width=True)
