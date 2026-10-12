# --- استبدل الكود من بداية القسم رقم 6 (Display Charts and Tables) بهذا الكود ---

# 6. Display Charts and Tables (Tabs for each discipline)
import altair as alt

tabs = st.tabs(disciplines)

def highlight_bottlenecks(val):
    if isinstance(val, (int, float)) and val < 0:
        return 'background-color: #ffcccc; color: #900000; font-weight: bold'
    return ''

for idx, disc in enumerate(disciplines):
    with tabs[idx]:
        st.markdown(f"### {disc} Team Analysis")
        
        results_df = pd.DataFrame({
            "Metric": ["Demand (Hrs)", "Capacity (Hrs)", "Variance (Shortage/Surplus)"],
        })
        
        var_list = []
        dem_list = []
        cap_list = []
        
        for i, w_label in enumerate(week_labels):
            dem = round(demand[disc][i], 1)
            cap = capacities[disc]
            var = round(cap - dem, 1)
            
            results_df[w_label] = [dem, cap, var]
            var_list.append(var)
            dem_list.append(dem)
            cap_list.append(cap)
            
        # Display Heatmap Table
st.dataframe(
    results_df.style
    .map(highlight_bottlenecks, subset=week_labels)
    .format("{:.2f}", subset=week_labels), 
    use_container_width=True
)        
        # Prepare Chart Data using actual dates to enforce chronological sorting
        chart_data = pd.DataFrame({
            "Week_Date": pd.to_datetime(weeks), # تاريخ حقيقي لضمان الترتيب الزمني
            "Week_Label": week_labels,
            "Variance": var_list,
            "Demand": dem_list,
            "Capacity": cap_list
        })
        
        # Determine Color: Green for Surplus (>= 0), Red for Shortage (< 0)
        chart_data['Color'] = np.where(chart_data['Variance'] >= 0, '#2ca02c', '#d62728')

        st.markdown("#### 📉 Weekly Variance Chart (Dips below 0 indicate bottlenecks)")
        
        # Create Bar Chart using Altair for explicit sorting and coloring
        bar_chart = alt.Chart(chart_data).mark_bar().encode(
            x=alt.X('Week_Date:T', 
                    axis=alt.Axis(title='Week', format='%d-%b', labelAngle=-45, tickCount=num_weeks)),
            y=alt.Y('Variance:Q', title='Variance (Hrs)'),
            color=alt.Color('Color:N', scale=None), # استخدام اللون المحدد في عمود Color مباشرة
            tooltip=['Week_Label', 'Variance']
        ).properties(
            height=400
        ).interactive()
        
        st.altair_chart(bar_chart, use_container_width=True)
        
        st.markdown("#### 📈 Demand vs Capacity Trend")
        
        # Prepare Data for Line Chart
        line_chart_data = chart_data.melt(id_vars=['Week_Date', 'Week_Label'], 
                                          value_vars=['Demand', 'Capacity'], 
                                          var_name='Metric', value_name='Hours')
        
        # Create Line Chart using Altair
        line_chart = alt.Chart(line_chart_data).mark_line(point=True).encode(
            x=alt.X('Week_Date:T', 
                    axis=alt.Axis(title='Week', format='%d-%b', labelAngle=-45, tickCount=num_weeks)),
            y=alt.Y('Hours:Q', title='Hours'),
            color=alt.Color('Metric:N', scale=alt.Scale(domain=['Demand', 'Capacity'], range=['#1f77b4', '#ff7f0e'])),
            tooltip=['Week_Label', 'Metric', 'Hours']
        ).properties(
            height=400
        ).interactive()
        
        st.altair_chart(line_chart, use_container_width=True)
