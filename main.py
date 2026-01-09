from pathlib import Path

import json
import httpx

query_url = "https://leetcode.cn/graphql/"

query_daily = """
query CalendarTaskSchedule($days: Int!) {
    calendarTaskSchedule(days: $days) {
        dailyQuestions { 
            name 
            slug 
            link 
        }
    }
}""".strip()

query_daily_details = """query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    questionFrontendId
    boundTopicId
    title
    titleSlug
    content
    translatedTitle
    translatedContent
    difficulty
    topicTags {
      name
      slug
      translatedName
      __typename
    }
  }
}""".strip()


def main():
    try:
        dailyQuestion = request(
            url=query_url,
            data={
                "operationName": "CalendarTaskSchedule",
                "variables": {"days": 0},
                "query": query_daily,
            },
        )["data"]["calendarTaskSchedule"]["dailyQuestions"][0]

        question_content = request(
            url=query_url,
            data={
                "operationName": "questionData",
                "variables": {"titleSlug": dailyQuestion["slug"]},
                "query": query_daily_details,
            },
        )["data"]["question"]

        data = {
            "id": question_content["questionFrontendId"],
            "title": question_content["title"],
            "title_zh": question_content["translatedTitle"],
            "slug": dailyQuestion["slug"],
            "link": dailyQuestion["link"],
            "content": question_content["content"],
            "translatedContent": question_content["translatedContent"],
            "difficulty": question_content["difficulty"],
            "topicTags": question_content["topicTags"],
        }

        fpath = Path("data/daily.json")

        save_json(fpath, data)
        print(fpath)
        print(str(data)[:500])
    except Exception as e:
        print(e)


def request(url, data):
    Headers = {
        "origin": "https://leetcode.cn",
        "referer": "https://leetcode.cn/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "content-type": "application/json",
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "accept-encoding": "gzip, deflate, br, zstd",
    }
    response = httpx.post(
        url,
        json=data,
        headers=Headers
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise httpx.ReadError(response.text)


def save_json(filepath: Path, args):
    if not Path.exists(filepath):
        Path.mkdir(filepath.parent)
    filepath.write_text(json.dumps(args, ensure_ascii=False, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
