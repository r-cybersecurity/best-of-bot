import boto3
import requests
import pprint

rank_settings = {
    "Business Security Questions &amp; Discussion": {
        "requirements": {"karma": 3, "ratio": 0.7, "comments": 4},
        "weights": {
            "karma": 1,
            "comments": 1,
        },
    },
    "Career Questions &amp; Discussion": {
        "requirements": {"karma": 5, "ratio": 0.8, "comments": 10},
        "weights": {
            "karma": 0.1,
            "comments": 0.15,
        },
    },
    "News - General": {
        "requirements": {"karma": 20, "ratio": 0.8, "comments": 6},
        "weights": {
            "karma": 0.05,
            "comments": 0.1,
        },
    },
    "News - Breaches &amp; Ransoms": {
        "requirements": {"karma": 20, "ratio": 0.8, "comments": 6},
        "weights": {
            "karma": 0.05,
            "comments": 0.075,
        },
    },
    "Corporate Blog": {
        "requirements": {"karma": 30, "ratio": 0.85, "comments": 10},
        "weights": {
            "karma": 0.05,
            "comments": 0.075,
        },
    },
}

client = boto3.client('dynamodb')

def logic_handler():
    url = "https://www.reddit.com/r/cybersecurity/hot/.json?count=25"
    headers = {"User-Agent": "r/cybersecurity Twitter Bot"}

    try:
        fetched_data = requests.get(url, headers=headers)
    except Exception:
        return 500, {"Reason": "Couldn't GET Reddit"}

    try:
        json_data = fetched_data.json()
    except Exception:
        return 500, {"Reason": "Reddit did not return valid JSON"}

    if "data" not in json_data:
        return 500, {"Reason": "Reddit did not return JSON with 'data' field."}

    try:
        qualifying_submissions = []
        for submission in json_data["data"]["children"]:
            submission_rank = submission_ranker(submission["data"])
            if submission_rank:
                qualifying_submissions.append(submission_rank)
    except Exception as e:
        return 500, {"Reason": f"Error while parsing submissions: {e}"}

    if len(qualifying_submissions) == 0:
        return 500, {"Reason": "No qualifying submissions found."}

    attempts = 0
    tweeted = False
    disqualified_submissions = []

    while attempts < len(qualifying_submissions) and not tweeted:
        attempts += 1
        stored_submission = {"priority": 0}

        for submission in qualifying_submissions:
            if not submission["link"] in disqualified_submissions:
                if submission["priority"] > stored_submission["priority"]:
                    stored_submission = submission
        
        disqualified_submissions.append(stored_submission["link"])
        print(str(stored_submission["priority"]) + " " + stored_submission["link"])
        
        # check in DynamoDB if the thing has been tweeted

    if tweeted:
        return 200, {"Reason": "Tweeted successfully."}
    if not tweeted:
        return 200, {"Reason": "Nothing to tweet; exhausted."}


def submission_ranker(submission):
    if submission["over_18"] == True:
        return False

    try:
        settings = rank_settings[submission["link_flair_text"]]
    except Exception:
        return False

    requirements = settings["requirements"]
    if (
        submission["ups"] < requirements["karma"]
        or submission["upvote_ratio"] < requirements["ratio"]
        or submission["num_comments"] < requirements["comments"]
    ):
        return False

    weights = settings["weights"]
    priority = (
        submission["upvote_ratio"]
        * submission["upvote_ratio"]
        * submission["ups"]
        * weights["karma"]
        * submission["num_comments"]
        * weights["comments"]
    )

    if priority < 5:
        return False

    return {
        "priority": priority,
        "link": submission["permalink"],
        "title": submission["title"],
    }
