import boto3
import json
import praw
import os
import time
from atproto import Client
from atproto.xrpc_client.models import AppBskyEmbedExternal
from html import escape, unescape
from botocore.exceptions import ClientError, NoCredentialsError
from pprint import pprint
from mastodon import Mastodon
from bs4 import BeautifulSoup


rank_settings = {
    "Ask Me Anything!": {
        "karma": 1,
        "comments": 1,
    },
    "Business Security Questions &amp; Discussion": {
        "karma": 0.5,
        "comments": 1,
    },
    "Research Article": {
        "karma": 0.2,
        "comments": 0.5,
    },
    "Threat Actor TTPs &amp; Alerts": {
        "karma": 0.2,
        "comments": 0.5,
    },
    "New Vulnerability Disclosure": {
        "karma": 0.2,
        "comments": 0.5,
    },
    "Career Questions &amp; Discussion": {
        "karma": 0.2,
        "comments": 0.25,
    },
    "Other": {
        "karma": 0.1,
        "comments": 0.25,
    },
    "News - General": {
        "karma": 0.05,
        "comments": 0.1,
    },
    "News - Breaches &amp; Ransoms": {
        "karma": 0.05,
        "comments": 0.1,
    },
    "Corporate Blog": {
        "karma": 0.05,
        "comments": 0.1,
    },
}


client = boto3.client("dynamodb")


def lambda_handler(event, context):
    reddit = praw.Reddit(
        client_id=os.getenv("PRAW_CLIENT_ID"),
        client_secret=os.getenv("PRAW_CLIENT_SECRET"),
        refresh_token=os.getenv("PRAW_REFRESH_TOKEN"),
        user_agent="r/cybersecurity 'best of' bot",
    )
    reddit.read_only = True

    qualifying_submissions = []
    for submission in reddit.subreddit("cybersecurity").hot(limit=25):
        post_created_epoch = submission.created_utc

        if time.time() < post_created_epoch + (15 * 60):
            # post is less than 15m old, strongly increases chance that the post
            # is unmoderated, for ex. AutoMod may not run for 0-3m in typical use
            continue

        submission_rank = submission_ranker(submission)
        if submission_rank:
            qualifying_submissions.append(submission_rank)

    if len(qualifying_submissions) == 0:
        return {"statusCode": 500, "body": "No qualifying submissions found."}

    attempts = 0
    posted = False
    disqualified_submissions = []

    while attempts < len(qualifying_submissions) and not posted:
        attempts += 1
        stored_submission = {"priority": 0}

        # identify which submission we want to post the most
        for submission in qualifying_submissions:
            if not submission["link"] in disqualified_submissions:
                if submission["priority"] > stored_submission["priority"]:
                    stored_submission = submission

        disqualified_submissions.append(stored_submission["link"])
        print(str(stored_submission["priority"]) + " " + stored_submission["link"])

        # check in DynamoDB if the submission has been posted
        dynamo_get = []
        try:
            dynamo_get = client.get_item(
                TableName="twitter_bot__r_cybersecurity",
                Key={"link": {"S": stored_submission["link"]}},
            )
        except ClientError as e:
            print(f"-- DynamoDB GET failed: {e.response['Error']['Message']}")
            # we don't know if we've posted this, so let's skip it
            # this enforces at most once posting
            continue
        except NoCredentialsError:
            # local devel without access to DDB, just keep going
            pass

        # we've confidently posted the submission, skip it
        if "Item" in dynamo_get:
            print("-- already posted, skipping")
            continue

        # we haven't posted the submission, try logging that we'll post it
        expires = str((14 * 24 * 60 * 60) + int(time.time()))  # 14 days from now
        try:
            client.put_item(
                TableName="twitter_bot__r_cybersecurity",
                Item={"link": {"S": stored_submission["link"]}, "ttl": {"N": expires}},
            )
        except ClientError as e:
            print(f"-- DynamoDB PUT failed: {e.response['Error']['Message']}")
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once posting
            continue
        except NoCredentialsError:
            # local devel without access to DDB, just keep going
            pass
        except Exception as e:
            print(e)
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once posting
            continue

        posted = True

        print("-- building post")
        title = unescape(stored_submission["title"])
        selftext_html = ""
        context = "View post on Reddit."

        if "selftext_html" in stored_submission.keys():
            selftext_html = unescape(stored_submission["selftext_html"])

            # clean irrelevant text from HTML
            soup = BeautifulSoup(selftext_html, features="html.parser")
            for script in soup(["script", "style"]):
                script.extract()

            # get clean selftext
            selftext = soup.get_text()

            # use as link context
            if len(selftext) > 200:
                context = selftext[:197] + "..."
            elif len(selftext) > 10:
                context = selftext

        # Mastodon counts URLs as a fixed 23 characters regardless of length, and
        # the link is appended with a leading space, so the summary has 24 chars of
        # headroom against the default 500-char limit.
        comments = fetch_comments(reddit, stored_submission["link"])
        toot_summary = summarize(title, selftext_html, comments, 476)

        # Bluesky caps posts at 300 characters. The link lives in the embed card,
        # not the post text, so the summary can use the full limit.
        skeet_summary = summarize(title, selftext_html, comments, 300)

        # shorten link by removing title component
        # still always counts as 23 characters though
        post_id = stored_submission["link"].strip("/").split("/")[3]
        post_link = f"https://reddit.com/r/cybersecurity/comments/{post_id}/"

        post_engine(post_toot, toot_summary, title, context, post_link)
        post_engine(post_skeet, skeet_summary, title, context, post_link)

    if posted:
        return {"statusCode": 200, "body": "Posted successfully."}
    if not posted:
        return {"statusCode": 200, "body": "Exhausted all options for posting."}


def post_engine(target, summary, title, context, link):
    prioritized_posts = [f"{summary}", f"{title}", ""]
    succeeded = False
    for post in prioritized_posts:
        clean_post = clean_tokens(post)
        if not succeeded:
            succeeded = target(clean_post, title, context, link)


def clean_tokens(text_data):
    tokens_to_clean = text_data.split(" ")

    clean_tokens = []
    for token_to_clean in tokens_to_clean:
        # could also ensure no cashtags?
        clean_token = token_to_clean.strip("#@")
        clean_tokens.append(clean_token)

    return " ".join(clean_tokens)


def post_toot(post, title, context, link):
    print("-- attempting toot")
    post_me = f"{post} {link}"

    try:
        MASTO_INSTANCE_URL = os.getenv("MASTO_INSTANCE_URL")
        MASTO_CLIENT_KEY = os.getenv("MASTO_CLIENT_KEY")
        MASTO_CLIENT_SECRET = os.getenv("MASTO_CLIENT_SECRET")
        MASTO_ACCESS_TOKEN = os.getenv("MASTO_ACCESS_TOKEN")

        if (
            MASTO_INSTANCE_URL
            and MASTO_CLIENT_KEY
            and MASTO_CLIENT_SECRET
            and MASTO_ACCESS_TOKEN
        ):
            mastodon = Mastodon(
                api_base_url=MASTO_INSTANCE_URL,
                client_id=MASTO_CLIENT_KEY,
                client_secret=MASTO_CLIENT_SECRET,
                access_token=MASTO_ACCESS_TOKEN,
            )
            mastodon.status_post(post_me, visibility="unlisted")  # conservative
            print(f"-- tooted {post_me}")
            return True
        else:
            print("-- environment variables not present to toot")
    except Exception as e:
        print(f"-- toot caused exception {str(e)}")
        return False


def post_skeet(post, title, context, link):
    print("-- attempting skeet")

    try:
        BSKY_USERNAME = os.getenv("BSKY_USERNAME")
        BSKY_PASSWORD = os.getenv("BSKY_PASSWORD")

        if BSKY_USERNAME and BSKY_PASSWORD:
            client = Client()
            client.login(BSKY_USERNAME, BSKY_PASSWORD)
            external_link = AppBskyEmbedExternal.External(
                uri=link,
                description=context,
                title=title,
            )
            client.send_post(
                text=post, embed=AppBskyEmbedExternal.Main(external=external_link)
            )
            print(f"-- skeeted {post}")
            return True
        else:
            print("-- environment variables not present to skeet")
    except Exception as e:
        print(f"-- skeet caused exception {str(e)}")
        return False


def fetch_comments(reddit, permalink):
    """Fetch the top comments for the single chosen post via PRAW, returning them
    as a newline-joined string so they can be included as extra context for the
    summarizer. Returns an empty string if no comments are available or if the
    fetch fails, so the caller proceeds without comment context."""
    try:
        submission = reddit.submission(url="https://reddit.com" + permalink)
        # Drop collapsed "load more" stubs without recursively fetching the whole
        # tree, so we stay bounded to the comments Reddit already returned.
        submission.comments.replace_more(limit=0)
        comments = submission.comments.list()
        top_comment = [
            c for c in comments if isinstance(c, praw.models.Comment) and hasattr(c, "body")
        ]
        # The default sort is by "top"; sort again by score and take the top 10
        # to be explicit about the cap, regardless of ordering quirks.
        top_comment.sort(key=lambda c: c.score, reverse=True)
        top_comment = top_comment[:10]
        if not top_comment:
            print("-- no comments to include, proceeding without them")
            return ""
        return unescape("\n".join(c.body for c in top_comment))
    except Exception as e:
        print(f"-- fetching comments failed ({str(e)}), proceeding without them")
        return ""


def submission_ranker(submission):
    if submission.over_18 == True:
        return False

    try:
        weights = rank_settings[submission.link_flair_text]
    except Exception:
        weights = rank_settings["Other"]

    priority = (
        submission.upvote_ratio
        * submission.upvote_ratio
        * submission.score
        * weights["karma"]
        * submission.num_comments
        * weights["comments"]
    )

    if priority < 10:
        return False

    selftext_html = ""
    if isinstance(submission.selftext_html, str):
        selftext_html = submission.selftext_html

    return {
        "priority": priority,
        "link": submission.permalink,
        "title": submission.title,
        "flair": submission.link_flair_text,
        "selftext_html": selftext_html,
    }


def summarize(title, selftext_html, comments, char_limit):
    bedrock = boto3.client("bedrock-runtime")
    # Claude Sonnet 4.6 is only invokable in us-west-2 via its US-region
    # inference profile (the bare model id rejects with on-demand-throughput
    # errors).
    model = "us.anthropic.claude-sonnet-4-6"

    system_prompt = (
        "You produce summaries for posts shared on Reddit's r/cybersecurity community, "
        "written for people on Mastodon and Bluesky who are not on Reddit. The pasted "
        "title and selftext are the Reddit post itself: either a shared external article "
        "or a discussion post where the poster asks a question. "
        "You may also be given a COMMENTS section containing the top comments on the "
        "post. The comments are context only: use them to understand the community's "
        "reaction, corrections, and additional detail, but do not summarize the "
        "comments themselves. The summary must describe the post (and the question or "
        "article it raises), not the comment thread. If an article post's comments "
        "discuss relevant unstated facts, you may fold those into the description, but "
        "never present reader opinion as fact. "
        "Your job is to help someone off-Reddit understand what the post is about and "
        "decide whether to click through. "
        "If the post is a question or discussion, summarize the question and the "
        "discussion the poster is raising - what the poster is asking and the key points "
        "or context of the debate - NOT any answer. Do not answer the question yourself "
        "and do not let the summary read as a definitive verdict; present it as an "
        "open question/discussion. "
        "If the post links to an external article or resource, describe what that "
        "clicked-link actually covers, using only facts present in the text. "
        "Lead with the most newsworthy, concrete detail (for example the affected "
        "software or CVE, the attacker, the vulnerability class, or the regulatory or "
        "business impact). "
        "Use only facts present in the text. "
        "Avoid hashtags, emoji, filler openers ('Here is...', 'This post is...', 'I'm "
        "sorry, I don't understand'), and meta-commentary. "
        "Explicit language is OK as long as it is not discriminatory. "
    )

    user_content = post_prep(title, selftext_html, comments)

    summary = invoke_summary(bedrock, model, system_prompt, user_content, char_limit)

    # Guard against the model declining or apologizing instead of summarizing.
    if any(
        token in summary.lower()
        for token in ("i'm sorry", "i am sorry", "i don't understand", "i do not understand")
    ):
        print(f"Model refused to summarize, disqualifying: {summary}")
        return title

    if len(summary) > char_limit:
        # Ask for a rewrite with a softer target so the model aims comfortably
        # under the hard cap instead of hugging it (reducing the chance the
        # retry lands over again). We also resend the original post content so
        # the rewrite isn't working from a bare instruction.
        retry_target = int(char_limit * 0.85)
        correction = (
            f"Your previous summary was too long: the requested length was "
            f"{char_limit} characters and you provided a response {len(summary)} "
            f"characters long. Rewrite it to a maximum of {retry_target} characters, "
            "aiming to land clearly under the hard cap so it is not truncated. Cut "
            "length by tightening wording, removing redundancy, and dropping optional "
            "clauses or examples, but keep the key facts. This is a hard requirement, "
            "not a suggestion: do not exceed the target. Reply with only the rewritten "
            "summary, no quotes or preamble."
        )
        shortened = invoke_summary(
            bedrock,
            model,
            system_prompt,
            user_content,
            char_limit,
            extra=correction,
            retry_target=retry_target,
        )
        if len(shortened) > char_limit:
            print(
                f"Summary still too long after retry ({len(shortened)} > {char_limit}), "
                "trimming to fit"
            )
            shortened = trim_to_fit(shortened, char_limit)
        summary = shortened

    return summary


def trim_to_fit(text, char_limit):
    """Trim text to fit char_limit, breaking at the last word boundary so the
    result does not end mid-word. Appends \"...\" only if something was cut."""
    if len(text) <= char_limit:
        return text
    cut = text[:char_limit - 3]
    idx = cut.rfind(" ")
    if idx > 0:
        return cut[:idx].rstrip() + "..."
    return cut.rstrip() + "..."


def invoke_summary(bedrock, model, system_prompt, user_content, char_limit, extra=None, retry_target=None):
    instruction = (
        f"Reply with only the summary itself, no quotes or preamble, in {char_limit} "
        "characters or fewer (this includes every character in your reply, so any "
        "leading/trailing whitespace, quotes, or code fences count toward the limit)."
    )
    if retry_target:
        instruction = (
            f"Reply with only the rewritten summary itself, no quotes or preamble, "
            f"in at most {retry_target} characters. Aim to come in comfortably under "
            f"the {char_limit} limit by tightening wording rather than dropping key "
            f"facts. Count every character, including punctuation and whitespace."
        )
    system = system_prompt + instruction
    # Always send the original post context so the model has the source text;
    # `extra` (if any) is appended as a follow-up user turn.
    messages = [{"role": "user", "content": user_content}]
    if extra:
        messages.append({"role": "assistant", "content": ""})
        messages.append({"role": "user", "content": extra})

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system,
        "messages": messages,
    }

    try:
        response = bedrock.invoke_model(
            modelId=model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body).encode("utf-8"),
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"].strip()
    except Exception as e:
        print(f"Bedrock threw exception {str(e)}, no summary today")
        return ""


def post_prep(title, selftext_html, comments=""):
    title = remove_multiple_spaces_from_string(title)
    text = remove_html_tags(selftext_html)

    # openai seems to do better without any newlines
    text = text.replace("\n", " ").replace("\r", "")
    text = remove_multiple_spaces_from_string(text)

    article = f"{title} ... {text}"

    if comments.strip():
        article += "\n\nCOMMENTS (context only, ignore if not relevant):\n" + comments.strip()

    return article


def remove_multiple_spaces_from_string(input):
    return " ".join(input.split())


def remove_html_tags(text):
    """Remove html tags from a string"""
    import re

    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)


if __name__ == "__main__":
    pprint(lambda_handler({}, {}))
