import matplotlib.pyplot as plt
import pandas as pd
import requests as rq
from datetime import datetime, timedelta
from datetime import date
headers = {
    "User-Agent": "GitLab CI automated test (/generated-data-platform/aqs/analytics-api) compare-page-metrics.py",
}

### AI generated
def date_between(start_date, end_date):
    ''' 
    Outputs a list of dates inclusive between start_date and end_date.
    '''
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")

    date_list = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range((end - start).days + 1)]
    return date_list
###

def top_articles(date):
    '''
    Collects articles with largest page views from the Wikimedia API for a given date
    Outputs a DataFrame with article names and view counts.
    '''
    date = str(date)
    date = date.replace("-", "")
    year, month, day = date[:4], date[4:6], date[6:8]
    
    top_url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{year}/{month}/{day}"

    top_response = rq.get(top_url, headers=headers).json()

    if list(top_response.keys())[0] == "detail":
        missing_data = True
        print(f"No data available for {date}")
        return pd.DataFrame(columns=["article", "views"])
    else:
        missing_data = False
    
    top_df = pd.DataFrame.from_records(top_response["items"][0]["articles"])
    top_df = top_df.drop(top_df.columns[-1], axis=1)

    # assumption: people mostly aren't interested in the main page, featured pictures, and special search page - so we drop them
    top_df = top_df[~top_df["article"].str.contains("Main_Page", na=False)]
    top_df = top_df[~top_df["article"].str.contains("Special:Search", na=False)]
    top_df = top_df[~top_df["article"].str.contains("Wikipedia:Featured_pictures", na=False)]

    if missing_data == True:
        print("Some data for requested date range is missing: possible requested article is a special page")

    return top_df

def sum_top_articles(date_list):
    '''
    Outputs dataframe of the top articles and their cumulative views across the date range.
    '''
    point_data = {"Top Articles": [], "Cumulative views": []}

    for date in date_list:
        top_df = top_articles(date)
        for index, row in top_df.iterrows():
            article = row["article"]
            views = row["views"]
            
            if article in point_data["Top Articles"]:
                idx = point_data["Top Articles"].index(article)
                point_data["Cumulative views"][idx] += views
            else:
                point_data["Top Articles"].append(article)
                point_data["Cumulative views"].append(views)

    totalviews_df = pd.DataFrame(point_data)
    totalviews_df = totalviews_df.sort_values(by="Cumulative views", ascending=False).reset_index(drop=True)
    print(f"from {date_list[0]} to {date_list[-1]} the top 10 articles were \n {totalviews_df.head(10)}")      

    return totalviews_df

def top_plot(date_list):
    # plot the number of edits over time for the top 5 articles
    start_date,end_date = date_list[0], date_list[-1]
    frequency = "daily"

    for article in totalviews_df["Top Articles"].head(5):
        print(article)
        # URL for edit number data
        edit_url = f"https://wikimedia.org/api/rest_v1/metrics/edits/per-page/en.wikipedia.org/{article}/all-editor-types/{frequency}/{start_date}/{end_date}"

        # Request all data from APIs and parse responses as JSON
        edit_response = rq.get(edit_url, headers=headers).json()

        if list(edit_response.keys())[0] == "detail":
            print(f"No data available for {date}")
            missing_data = True
            continue
        else:
            missing_data = False
        
        # Create Pandas DataFrame for edit data
        edit_df = pd.DataFrame.from_records(edit_response["items"][0]["results"])

        # Parse timestamp and use it as index
        edit_df["timestamp"] = pd.to_datetime(edit_df["timestamp"])
        edit_df = edit_df.set_index("timestamp")

        plt.suptitle(f"Number of edits from {date_list[0][6:8]}/{date_list[0][4:6]}/{date_list[0][0:4]} to {date_list[-1][6:8]}/{date_list[-1][4:6]}/{date_list[-1][0:4]} of the most popular articles of that time")
        plt.xlabel("Date")
        plt.ylabel("Number of edits")
        plt.plot(edit_df.index, edit_df["edits"], label=article)
        plt.legend()

    plt.show()
    if missing_data == True:
        print("Some data for requested date range is missing: possible API hasn't updated yet!")

# Generate list of dates between start_date and end_date
Want_latest_date = True
no_days = 2
offset_days = 100
if Want_latest_date:
    end_date = date.today() - timedelta(days= offset_days)
    start_date = end_date - timedelta(days= no_days)

    date_list = date_between(str(start_date).replace("-",""), str(end_date).replace("-",""))
else:
    date_list = date_between("20250901", "20250930")

# Gives cumulative page views for top articles over the date range
totalviews_df = sum_top_articles(date_list)

# Plot edits for the top 5 articles
top_plot(date_list)