import boto3
import praw
import hashlib
import os
import re
import time
from atproto import Client, Request, models
from html import escape, unescape
from botocore.exceptions import ClientError, NoCredentialsError
from pprint import pprint
from mastodon import Mastodon
from bs4 import BeautifulSoup
from openrouter import OpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig


# Summarizer system prompt. Kept at the top of the file, separate from the
# request plumbing, so it can be edited without touching the code around it.
SUMMARIZER_SYSTEM_PROMPT = """THE TASK
You write summaries of posts from Reddit's r/cybersecurity for people reading
on Mastodon and Bluesky who are not on Reddit. The account publishing these
posts is 'Best of r/cybersecurity' (Bluesky @cybersecurity.page; Mastodon
@r_cybersecurity@infosec.exchange), so its audience already knows the content
is from Reddit and from r/cybersecurity. Your job is to help someone off-Reddit
understand what the post is about and decide whether to click through.

THE INPUT
You are given a title, the post's selftext, and optionally a COMMENTS section
with the top comments on the post. The title and selftext are the post itself:
either a shared external article or a discussion post where the poster asks a
question. The comments are context only: use them to understand the community's
reaction, corrections, and additional detail, but do not summarize the comments
themselves. If an article post's comments discuss relevant unstated facts, you
may fold those into the description, but never present reader opinion as fact.

PARAMETERS
- Reply with only the summary, nothing else: no quotes, preamble, or commentary.
- Use only facts present in the text. Never invent facts, names, numbers,
  dates, quotes, or citations.
- Never restate the Reddit context: do not write 'on Reddit',
  'r/cybersecurity', 'Reddit post', 'Reddit user', or similar.
- If the post is a question or discussion, summarize the question and the
  debate the poster is raising, not the answer. Do not answer the question
  yourself and do not let the summary read as a verdict; keep it an open
  question.
- If the post links to an external article, describe what that article
  actually covers, using only facts present in the text.
- Lead with the most newsworthy, concrete detail: the affected software or
  CVE, the attacker, the vulnerability class, or the business or regulatory
  impact.
- The summary must describe the post, not the comment thread.

TERMINOLOGY: USE SECURITY WORDS EXACTLY
In security writing, one swapped term changes what readers believe happened.
Precision outranks drama, and the correct term usually fits in fewer
characters anyway. These distinctions hold even in a short summary.
- If the post uses a term correctly, mirror it.
- If the post misuses a term, quietly use the correct one instead. Never
  repeat the error, never flag the correction, never blame the poster.
- Never inflate a claim through vocabulary: an exposed server is not a
  proven breach, a proof-of-concept is not an in-the-wild exploit, a
  scanner finding is not a confirmed compromise.
- When the facts are thin, describe what mechanically happened rather than
  reaching for the most alarming label available.

Common mix-ups, with the correct usage described first:
- Encryption vs encoding: encryption uses a key so only keyholders can read
  the data. Base64, hex, URL-encoding, gzip, and ROT13 are encodings that
  anyone can reverse and that provide zero secrecy. Never call Base64
  'encryption'; call it 'encoded'. Credentials hidden with Base64 are
  disguised, not protected.
- Hashing vs encryption: hashing is one-way and cannot be undone. If hashed
  passwords were attacked, they were 'cracked', never 'decrypted'. A salted
  hash is still not encryption.
- Obfuscation vs encryption: packed binaries, mangled strings, and renamed
  functions obfuscate; they hide intent, not content. Reserve 'encrypted'
  for keyed cryptography.
- Vulnerability vs exploit vs threat vs risk: a vulnerability is the
  weakness (tracked as a CVE), an exploit is code or technique that
  leverages it, a threat actor is who would use it, and risk weighs
  likelihood against impact. Do not write that 'an exploit was disclosed'
  unless actual PoC code exists; an advisory alone describes a
  vulnerability.
- Zero-day vs n-day: zero-day means exploited or traded before any vendor
  patch exists. Once a patch ships it is a known (n-day) vulnerability,
  even if most systems remain unpatched.
- CVE vs CVSS vs CWE: the CVE ID names one vulnerability, the CVSS score
  rates its severity, CWE classifies the weakness type. Never write
  'CVE 9.8' or 'a CWE of 8.6'; scores attach to CVE IDs, not CWE classes.
- Breach vs exposure vs leak: a breach means an attacker extracted data. A
  misconfigured storage bucket, open database, or published API key is an
  exposure until someone demonstrates data was taken. Never describe an
  open bucket as 'hacked'.
- Ransomware and malware families: ransomware encrypts victims' files to
  extort payment; that is hostile use of encryption, never protective.
  Worms self-replicate, trojans masquerade as legitimate software,
  info-stealers harvest credentials, a RAT grants remote control, and a
  botnet is the fleet of infected machines rather than one sample.
- Phishing vs spam: phishing manipulates a person into surrendering access
  or credentials; spam is unsolicited bulk mail. Spear-phishing targets
  named individuals, smishing arrives by SMS, vishing by phone call.
  Phishing that defeats MFA with real-time relay proxies is still phishing,
  not 'hacking'.
- DoS vs DDoS: denial of service can come from one machine; DDoS requires
  many sources acting in concert. Say 'distributed' only when multiple
  origins are established.
- IDS vs IPS: intrusion detection alerts after seeing malicious traffic;
  intrusion prevention sits inline and blocks it. An IDS cannot stop the
  attack it detects.
- Pentest vs red team vs bug bounty vs vulnerability scan: a pentest is
  scoped, authorized attack testing; a red team emulates a real adversary
  to test detection and response; a bug bounty pays outside researchers to
  report flaws; a vulnerability scan is an automated sweep for known
  issues. Never call an automated scanner run a 'penetration test'.
- Authentication vs authorization: authentication proves identity;
  authorization decides what that identity may touch. MFA strengthens
  login but fixes neither broken authorization nor stolen sessions.
- Passkeys vs OTP codes: passkeys are phishing-resistant cryptographic
  credentials that replace passwords; one-time codes sent by SMS or
  authenticator app are a second factor and are strictly weaker. Never
  call an SMS code 'unhackable' or equate it with a passkey.
- Session theft vs credential theft: stolen cookies or tokens let an
  attacker act as the victim without ever learning the password. Say
  'session hijacking' or 'token theft', not 'cracked the password'.
- Supply chain attack vs vendor breach: a supply chain attack poisons
  software the vendor distributes, compromising customers downstream; a
  vendor breach exposes the vendor's own environment. A poisoned update is
  supply chain; a stolen database dump is not.

WRITING STYLE AND VOICE
Write like a dry, world-weary security journalist who has seen it all before:
someone who has patched one too many ActiveMQ boxes and long ago stopped
being surprised. Deadpan and understated: say alarming things calmly, and let
the facts do the work. 'This is not ideal' is closer to the mark than 'this
is a disaster'. A wry aside or two per summary is welcome, for example
describing an organization that ignored nine disclosure emails as having no
functioning intake process, or noting that a 13-year-old flaw finally ran
out of places to hide. The humor is a quiet observation about the facts, not
a punchline bolted onto them. Aim it at vendor marketing, hype, and the
eternal comedy of other people's incident response. Punch up, never down: it
is fine to be sharply funny about vendors, big tech, breach brokers, and
management, and never funny at the expense of victims, small teams,
researchers, or people asking honest questions. Be skeptical of claims and
call out spin when you can see it, but do not editorialize about the poster.
Semi-professional: you can be blunt and use plain language, but you are
writing for a professional audience, so stay sharp and informed rather than
sloppy. Avoid gushing, superlatives, and hype. End on the last concrete
fact; do not add a generic upbeat closer.

HARD RULES
- Never restate the Reddit context: do not write 'on Reddit', 'r/cybersecurity',
  'Reddit post', 'Reddit user', or similar. The audience already knows.
- No em dashes or en dashes. Use periods, commas, colons, or parentheses
  instead.
- No AI tells: no 'delve', 'landscape', 'tapestry', 'testament', 'pivotal',
  'underscore', 'vibrant', 'showcase', 'crucial', 'elevate', 'foster', or
  similar inflated vocabulary. No 'not only... but also...' constructions, no
  tailing negations, and no rule-of-three lists.
- No superficial '-ing' phrases tacked on for fake depth ('highlighting...',
  'underscoring...', 'showcasing...').
- No filler openers ('Here is...', 'This post is...', 'Let's dive into...'),
  no apologies, no 'I hope this helps', no signposting, no meta-commentary.
- No manufactured drama: do not stack short dramatic fragments. One short
  sentence for emphasis is fine; a run of them is not.
- Prefer active voice and plain 'is', 'are', and 'has' constructions.
- Vary sentence length. Write the way a good human writer would.
- No hashtags, emojis, boldface, or curly quotation marks. Straight quotes
  only.
- Explicit language is fine as long as it is not discriminatory.
"""

# Any response shorter than this is not a real summary (for example a provider
# returning a reasoning-only or empty completion) and gets retried.
MIN_SUMMARY_LENGTH = 40

# The OpenRouter SDK applies its own internal retry loop on 5xx and stalled
# providers, with a default max_elapsed_time of one hour (see openrouter's
# RetryConfig/BackoffStrategy). That can keep a single chat.send() alive far
# past the Lambda's 15-minute timeout, so the per-request timeout_ms is never
# reached. The summarizer already owns retry policy (three bounded attempts in
# invoke_summary), so disable SDK-level retries and let timeout_ms bound each
# request.
NO_RETRY = RetryConfig(
    strategy="none",
    backoff=BackoffStrategy(
        initial_interval=0,
        max_interval=0,
        exponent=1.0,
        max_elapsed_time=0,
    ),
    retry_connection_errors=False,
)


class SummaryGenerationError(RuntimeError):
    """Raised when the summarizer cannot produce a valid summary after all
    retries. Propagates out of the Lambda so failures are loud, never silently
    falling back to posting the raw title."""


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
            # Post is less than 15 minutes old, which strongly increases the
            # chance that it is unmoderated; for example, AutoMod may not run
            # for 0-3 minutes in typical use.
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

        # Identify which submission we want to post the most.
        for submission in qualifying_submissions:
            if not submission["link"] in disqualified_submissions:
                if submission["priority"] > stored_submission["priority"]:
                    stored_submission = submission

        disqualified_submissions.append(stored_submission["link"])
        print(str(stored_submission["priority"]) + " " + stored_submission["link"])

        # Check in DynamoDB if the submission has been posted.
        dynamo_get = []
        try:
            dynamo_get = client.get_item(
                TableName="twitter_bot__r_cybersecurity",
                Key={"link": {"S": stored_submission["link"]}},
            )
        except ClientError as e:
            print(f"-- DynamoDB GET failed: {e.response['Error']['Message']}")
            # We don't know if we've posted this, so skip it.
            # This enforces at-most-once posting.
            continue
        except NoCredentialsError:
            # Local development without access to DDB; just keep going.
            pass

        # We've confidently posted the submission, so skip it.
        if "Item" in dynamo_get:
            print("-- already posted, skipping")
            continue

        # Build the post and generate summaries before claiming the post in
        # DynamoDB. If the LLM provider is stalled or failing, this fails loudly
        # without marking the post as shared, so a later run can still pick it up
        # instead of permanently skipping a post that was never actually posted.
        print("-- building post")
        title = unescape(stored_submission["title"])
        selftext_html = ""
        context = "View post on Reddit."

        if "selftext_html" in stored_submission.keys():
            selftext_html = unescape(stored_submission["selftext_html"])

            # Clean irrelevant text from the HTML.
            soup = BeautifulSoup(selftext_html, features="html.parser")
            for script in soup(["script", "style"]):
                script.extract()

            # Get the clean selftext.
            selftext = soup.get_text()

            # Use it as link context.
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

        # Claim the submission atomically. The conditional put means only the
        # first invocation to reach this point for a given post wins, so even if
        # two runs race on the same post, only one can post it (no duplicates).
        # TTL expires 14 days from now.
        expires = str((14 * 24 * 60 * 60) + int(time.time()))
        try:
            client.put_item(
                TableName="twitter_bot__r_cybersecurity",
                Item={"link": {"S": stored_submission["link"]}, "ttl": {"N": expires}},
                ConditionExpression="attribute_not_exists(link)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                print("-- another run claimed this post, skipping")
            else:
                print(f"-- DynamoDB PUT failed: {e.response['Error']['Message']}")
            # We don't know if we've saved this, so skip it.
            # This enforces at-most-once posting.
            continue
        except NoCredentialsError:
            # Local development without access to DDB; just keep going.
            pass
        except Exception as e:
            print(e)
            # We don't know if we've saved this, so skip it.
            # This enforces at-most-once posting.
            continue

        posted = True

        # Shorten the link by removing the title component.
        # It still always counts as 23 characters though.
        post_id = stored_submission["link"].strip("/").split("/")[3]
        post_link = f"https://reddit.com/r/cybersecurity/comments/{post_id}/"

        post_engine(post_toot, toot_summary, title, context, post_link)
        post_engine(post_skeet, skeet_summary, title, context, post_link)

    if posted:
        return {"statusCode": 200, "body": "Posted successfully."}
    if not posted:
        return {"statusCode": 200, "body": "Exhausted all options for posting."}


def retry_post(target, post, title, context, link, tries):
    """Call ``target`` up to ``tries`` times until one succeeds, returning True
    on success and False otherwise. Used to ride out transient provider errors
    when posting."""
    for attempt in range(1, tries + 1):
        if attempt > 1:
            print(f"-- post failed, retrying (attempt {attempt}/{tries})")
        if target(post, title, context, link):
            return True
    return False


def post_engine(target, summary, title, context, link):
    """Post the summary first, then the title, then a bare post, in that order.
    Each candidate gets a few tries to ride out transient errors, and every
    fallback is logged loudly so degradations are visible in CloudWatch."""
    candidates = (
        (f"{summary}", "summary", 3),
        (f"{title}", "title", 3),
        ("", "bare post", 1),
    )
    for index, (post, label, tries) in enumerate(candidates):
        clean_post = clean_tokens(post)
        if retry_post(target, clean_post, title, context, link, tries):
            return
        if index < len(candidates) - 1:
            next_label = candidates[index + 1][1]
            print(
                f"-- {label} failed after {tries} attempts, "
                f"falling back to {next_label}"
            )


def clean_tokens(text_data):
    tokens_to_clean = text_data.split(" ")

    clean_tokens = []
    for token_to_clean in tokens_to_clean:
        # Could also strip cashtags here.
        clean_token = token_to_clean.strip("#@")
        clean_tokens.append(clean_token)

    return " ".join(clean_tokens)


def exception_detail(e):
    """Return a diagnosable message for an exception. atproto request errors
    either leave str(e) empty (bare InvokeTimeoutError/NetworkError raised from
    httpx failures) or store the API error body on e.response.content
    (BadRequestError and friends), so surface both explicitly."""
    detail = ""
    response = getattr(e, "response", None)
    content = getattr(response, "content", None) if response is not None else None
    if isinstance(content, dict):
        detail = str(content)
    elif content is not None:
        error = getattr(content, "error", "")
        message = getattr(content, "message", "")
        detail = f"{error}: {message}".strip(": ") or str(content)
    message = str(e)
    return (
        f"{type(e).__name__}: {message} ({detail})"
        if detail
        else f"{type(e).__name__}: {message}"
    )


S32_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def s32_encode(value):
    """Encode a non-negative integer with atproto's s32 (base32) alphabet."""
    if value == 0:
        return ""
    chars = []
    while value:
        chars.append(S32_ALPHABET[value % 32])
        value //= 32
    return "".join(reversed(chars))


def stable_record_key(*parts):
    """Deterministic key derived from the post content, used as a Mastodon
    idempotency key. A retry after an ambiguous failure (timeout, 5xx) sends the
    same key, so Mastodon returns the existing status instead of posting a
    duplicate."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def stable_tid(*parts):
    """Deterministic Bluesky record key (a valid TID) derived from the post
    content and a coarse time bucket, so a retry after an ambiguous failure
    writes the same key and cannot create a duplicate post. The time bucket
    keeps TIDs roughly chronological while staying stable across retries."""
    digest = int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest(), "big")
    time_bucket = (int(time.time() * 1000) // 600000) * 600000  # 10-minute bucket
    timestamp = time_bucket * 1000 + (digest % 1000)
    clockid = (digest >> 10) % 32
    return s32_encode(timestamp) + s32_encode(clockid).rjust(2, "2")


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
            # Conservative: keep posts out of public timelines. The idempotency
            # key makes retries safe: Mastodon returns the same status instead
            # of posting a duplicate.
            mastodon.status_post(
                post_me,
                visibility="unlisted",
                idempotency_key=stable_record_key(post_me),
            )
            print(f"-- tooted {post_me}")
            return True
        else:
            print("-- environment variables not present to toot")
    except Exception as e:
        print(f"-- toot caused exception {exception_detail(e)}")
        return False


def post_skeet(post, title, context, link):
    print("-- attempting skeet")

    try:
        BSKY_USERNAME = os.getenv("BSKY_USERNAME")
        BSKY_PASSWORD = os.getenv("BSKY_PASSWORD")

        if BSKY_USERNAME and BSKY_PASSWORD:
            # The SDK defaults to httpx's 5-second timeout, which is too tight
            # for a briefly slow PDS; use a generous timeout so a momentary
            # slowdown doesn't kill the post.
            client = Client(request=Request(timeout=30))
            client.login(BSKY_USERNAME, BSKY_PASSWORD)
            external_link = models.AppBskyEmbedExternal.External(
                uri=link,
                description=context,
                title=title,
            )
            # Write with a deterministic record key derived from the content, so
            # a retry after a timeout or 5xx writes the same key and cannot
            # create a duplicate post.
            client.com.atproto.repo.create_record(
                models.ComAtprotoRepoCreateRecord.Data(
                    repo=client.me.did,
                    collection="app.bsky.feed.post",
                    rkey=stable_tid(post, title, context, link),
                    record=models.AppBskyFeedPost.Record(
                        created_at=client.get_current_time_iso(),
                        text=post,
                        embed=models.AppBskyEmbedExternal.Main(external=external_link),
                        langs=["en"],
                    ),
                )
            )
            print(f"-- skeeted {post}")
            return True
        else:
            print("-- environment variables not present to skeet")
    except Exception as e:
        detail = exception_detail(e)
        # A duplicate record key means the PDS already holds this post (created
        # by an earlier attempt whose response was lost), which is a success.
        if "already has record" in detail:
            print("-- skeet already posted, treating as success")
            return True
        print(f"-- skeet caused exception {detail}")
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
            c
            for c in comments
            if isinstance(c, praw.models.Comment) and hasattr(c, "body")
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
    model = "deepseek/deepseek-v4-flash-0731"

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # Fail loudly rather than silently producing no summary (which would
        # otherwise fall back to posting the raw title). A missing key means
        # the bot is misconfigured and we want to know about it.
        raise RuntimeError(
            "OPENROUTER_API_KEY environment variable is not set; "
            "refusing to silently skip summary generation"
        )

    user_content = post_prep(title, selftext_html, comments)

    with OpenRouter(api_key=api_key, retry_config=NO_RETRY) as open_router:
        return invoke_summary(open_router, model, user_content, char_limit)


def invoke_summary(open_router, model, user_content, char_limit):
    instruction = (
        f"Reply with only the summary itself, no quotes or preamble, in {char_limit} "
        "characters or fewer (this includes every character in your reply, so any "
        "leading/trailing whitespace, quotes, or code fences count toward the limit)."
    )
    system = SUMMARIZER_SYSTEM_PROMPT + "\n\n" + instruction
    messages = [{"role": "system", "content": system}]
    messages.append({"role": "user", "content": user_content})

    disqualify_reason = (
        "Your previous response was disqualified because it did not follow the "
        "task instructions: it refused, apologized, or said it could not do the "
        "task, it restated the Reddit context, or it was too short to be a real "
        "summary. Do not apologize, decline, explain, or mention Reddit or "
        "r/cybersecurity. Reply with only the summary itself."
    )
    # Softer target for over-limit rewrites so the model aims comfortably under
    # the hard cap instead of hugging it (reducing the chance the retry lands
    # over again).
    retry_target = int(char_limit * 0.85)

    # Be kind to OpenRouter providers: if they are struggling under load, an
    # immediate retry just adds to the pile. Wait a bit, with backoff, before
    # the 2nd and 3rd attempts. This bot runs hourly, so the extra latency is
    # not a concern.
    retry_delays = (3, 6)

    last_error = None
    for attempt in range(1, 4):
        if attempt > 1:
            delay = retry_delays[attempt - 2]
            print(f"-- waiting {delay}s before attempt {attempt}/3")
            time.sleep(delay)
        try:
            response = open_router.chat.send(
                model=model,
                messages=messages,
                max_tokens=32768,  # Cap the total output budget (reasoning + response).
                temperature=0.4,
                # Route to the cheapest provider serving the model (sort by minimum
                # price, no provider pinned), with graceful fallback if it errors.
                # Softly prefer providers that sustain at least 25 tokens/sec;
                # slower endpoints are only deprioritized, never excluded.
                provider={
                    "sort": "price",
                    "allow_fallbacks": True,
                    "preferred_min_throughput": 25,
                },
                # DeepSeek V4 Flash supports thinking; keep it light for summaries.
                reasoning={"effort": "low"},
                # Bound each request so a stalled provider cannot hang the whole
                # invocation; the retry loop above owns the retry policy.
                timeout_ms=120000,
            )
            summary = message_text(response.choices[0].message).strip()
        except Exception as e:
            last_error = e
            print(f"-- summary attempt {attempt}/3 threw exception: {str(e)}")
            continue

        if is_disqualified(summary):
            print(f"-- summary attempt {attempt}/3 disqualified: {summary}")
            # Nudge the model back on task instead of letting it repeat itself.
            messages.append({"role": "assistant", "content": summary})
            messages.append({"role": "user", "content": disqualify_reason})
            continue

        if is_over_limit(summary, char_limit):
            print(
                f"-- summary attempt {attempt}/3 over limit ({len(summary)} > {char_limit})"
            )
            over_limit_reason = (
                f"Your previous summary was {len(summary)} characters long, over the "
                f"{char_limit} character limit. Rewrite it to a maximum of {retry_target} "
                "characters, aiming to land clearly under the hard cap so it is not "
                "truncated. Cut length by tightening wording, removing redundancy, and "
                "dropping optional clauses or examples, but keep the key facts. This is "
                "a hard requirement, not a suggestion: do not exceed the target. Reply "
                "with only the rewritten summary, no quotes or preamble."
            )
            messages.append({"role": "assistant", "content": summary})
            messages.append({"role": "user", "content": over_limit_reason})
            continue

        return summary

    # Never silently degrade to the title: if the model cannot produce a valid
    # summary in three attempts, surface it as an error so it gets noticed.
    if last_error:
        raise SummaryGenerationError(
            f"no summary after 3 attempts, last error: {last_error}"
        ) from last_error
    raise SummaryGenerationError(
        "no summary after 3 attempts: every response was disqualified, over "
        f"the {char_limit} character limit, or both"
    )


def is_disqualified(summary):
    """Return True when the model refused, apologized, or claimed it could not
    do the task instead of producing a summary, when it restated the Reddit
    context the prompt explicitly forbids mentioning, or when the response is
    too short to be a real summary."""
    lowered = summary.lower()
    if len(summary) < MIN_SUMMARY_LENGTH:
        return True
    if any(
        token in lowered
        for token in (
            "i'm sorry",
            "i am sorry",
            "i don't understand",
            "i do not understand",
        )
    ):
        return True
    if re.search(r"\breddit\b|r/cybersecurity", lowered):
        return True
    return False


def is_over_limit(summary, char_limit):
    """Return True when the summary exceeds the hard character limit."""
    return len(summary) > char_limit


def message_text(message):
    """Extract plain text from an SDK assistant message. Content is normally a
    plain string, but with reasoning enabled some providers return a list of
    typed content parts, so handle both."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "text"):
                parts.append(item.text)
            elif hasattr(item, "raw") and isinstance(item.raw, dict):
                parts.append(item.raw.get("text", ""))
        return "".join(parts)
    return ""


def post_prep(title, selftext_html, comments=""):
    title = remove_multiple_spaces_from_string(title)
    text = remove_html_tags(selftext_html)

    # The LLM seems to do better without any newlines.
    text = text.replace("\n", " ").replace("\r", "")
    text = remove_multiple_spaces_from_string(text)

    article = f"{title} ... {text}"

    if comments.strip():
        article += (
            "\n\nCOMMENTS (context only, ignore if not relevant):\n" + comments.strip()
        )

    return article


def remove_multiple_spaces_from_string(input):
    return " ".join(input.split())


def remove_html_tags(text):
    """Remove HTML tags from a string."""
    import re

    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)


if __name__ == "__main__":
    pprint(lambda_handler({}, {}))
