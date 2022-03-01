import argparse
import sqlite3
from pprint import pprint
from sqlite3 import Error


def create_connection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
    except Error as e:
        print(e)

    return conn


def get_only_all_tweets(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tweets")

    rows = [dict(row) for row in cursor.fetchall()]
    return rows


def simplify_tweets(rows):
    common = []
    for row in rows:
        common_row = simple_tweet_format(
            row["screen_name"],
            row["tweet"],
        )
        common.append(common_row)
    return common


def simple_tweet_format(author, content):
    return {
        "author": author,
        "content": content,
    }


def get_only_tweets_from_twint(db_file):
    print("Loading tweets from sqlite database")
    conn = create_connection(db_file)
    rows = get_only_all_tweets(conn)
    print("Got raw tweets from sqlite database, simplifying")
    common = simplify_tweets(rows)
    return common


parser = argparse.ArgumentParser(
    description="Fetches data from a number of sources and compiles a training set"
)
parser.add_argument(
    "--sqlite-twint", action="store", type=str, required=True, help="Where the bird site is stored"
)
args = parser.parse_args()

data = get_only_tweets_from_twint(args.sqlite_twint)

print("Counting the number of times each user used a unique hashtag")
unique_hashtag_uses = {}
unique_hashtag_deduplicator = []
for tweet in data:
    tokens = tweet["content"].split(" ")
    for token in tokens:
        if token.startswith("#") and len(token) > 2:
            token = token.rstrip(" .!?,").lower()
            unique_key = f'{tweet["author"]} + {token}'
            if not unique_key in unique_hashtag_deduplicator:
                unique_hashtag_deduplicator.append(unique_key)
                if token in unique_hashtag_uses.keys():
                    unique_hashtag_uses[token] += 1
                else:
                    unique_hashtag_uses[token] = 1

for hashtag, count in unique_hashtag_uses.items():
    if count > 10:
        print(f'"{hashtag}": {count},')
