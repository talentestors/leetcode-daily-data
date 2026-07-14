import json
import re
import os
import sys  # 新增：引入 sys 模块用于退出程序
import zoneinfo
import asyncio
import httpx
from pathlib import Path
from datetime import datetime
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# ================= 配置区 =================
QUERY_URL = "https://leetcode.cn/graphql"

# 1. 从环境变量读取 Cookie (用于 GitHub Actions)
LEETCODE_COOKIE = os.environ.get("LEETCODE_COOKIE", "")

HEADERS = {
    # 2. 更新 User-Agent 到较新版本
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://leetcode.cn/",
    "Origin": "https://leetcode.cn",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    
    # 3. 增加现代浏览器的 Sec- 系列请求头，降低被 WAF 识别为机器人的概率
    "Sec-Ch-Ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="8"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# 4. 动态注入 Cookie
if LEETCODE_COOKIE:
    HEADERS["Cookie"] = LEETCODE_COOKIE
    print("[Info] LeetCode Cookie loaded from environment.")
else:
    print("[Warning] No LEETCODE_COOKIE found in environment. WAF might block the request.")

# ==========================================

QUERY_DAILY = """
query CalendarTaskSchedule($days: Int!) {
    calendarTaskSchedule(days: $days) {
        dailyQuestions { 
            name 
            slug 
            link 
        }
    }
}
""".strip()

QUERY_DAILY_DETAILS = """
query questionData($titleSlug: String!) {
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
    }
  }
}
""".strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(
        (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError, ValueError)
    ),
)
async def request_async(url, data, timeout=15.0):
    """Async HTTP request with retry and error handling"""
    # 5. 关键修改：将 http2=True 改为 http2=False
    # httpx 的 HTTP/2 实现 TLS 指纹极易被阿里云盾识别，降级为 HTTP/1.1 更稳定
    async with httpx.AsyncClient(
        http2=False, headers=HEADERS, timeout=timeout
    ) as client:
        try:
            response = await client.post(url, json=data, follow_redirects=True)
            response.raise_for_status()

            # Check if response is JSON (WAF 拦截时通常返回 HTML)
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type.lower():
                # 如果返回 HTML，说明被 WAF 拦截了
                if "<title>阻断页面</title>" in response.text:
                    raise ValueError("Request blocked by WAF (Cloudflare/Aliyun). Check Cookie or IP.")
                raise ValueError(f"Unexpected content type: {content_type}")

            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text[:500] if e.response else "No response body"
            raise Exception(
                f"HTTP error {e.response.status_code}: {error_detail}"
            ) from e
        except json.JSONDecodeError as e:
            raise Exception(f"JSON decode error: {e.doc[:500]}") from e


def clean_html_content(html_content: str) -> str:
    """Clean HTML content by removing tags and special characters"""
    if not html_content:
        return ""

    text = html_content
    text = re.sub(r"\n", "", text)
    text = re.sub(r"\t", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
    return text


def save_json(filepath: Path, data: dict):
    """Safely save JSON file"""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving file: {e}")
        return False


async def main_async():
    """Async main function"""
    fpath = Path("data/daily.json")

    try:
        print("Fetching fresh data from LeetCode...")

        # Fetch daily question information
        daily_response = await request_async(
            QUERY_URL,
            {
                "operationName": "CalendarTaskSchedule",
                "variables": {"days": 0},
                "query": QUERY_DAILY,
            },
        )

        daily_questions = (
            daily_response.get("data", {})
            .get("calendarTaskSchedule", {})
            .get("dailyQuestions", [])
        )
        if not daily_questions:
            raise ValueError("No daily questions found in response")

        daily_question = daily_questions[0]

        # Fetch question details
        question_response = await request_async(
            QUERY_URL,
            {
                "operationName": "questionData",
                "variables": {"titleSlug": daily_question["slug"]},
                "query": QUERY_DAILY_DETAILS,
            },
        )

        question_data = question_response.get("data", {}).get("question", {})
        if not question_data:
            raise ValueError("No question data found in response")

        # Clean and construct final data
        cleaned_content = clean_html_content(question_data.get("translatedContent", ""))

        data = {
            "id": question_data.get("questionFrontendId", ""),
            "title": question_data.get("title", ""),
            "title_zh": question_data.get("translatedTitle", ""),
            "slug": daily_question.get("slug", ""),
            "link": daily_question.get("link", ""),
            "content": clean_html_content(question_data.get("content", "")),
            "translatedContent": cleaned_content,
            "difficulty": question_data.get("difficulty", ""),
            "topicTags": [
                {
                    "name": tag.get("name", ""),
                    "slug": tag.get("slug", ""),
                    "translatedName": tag.get("translatedName", ""),
                }
                for tag in question_data.get("topicTags", [])
            ],
            "date": datetime.now(zoneinfo.ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"),
        }

        # Save data
        if save_json(fpath, data):
            print(f"Successfully saved to {fpath}")
            print(f"Data preview: {str(data)[:200]}\n")
            # print(f"Content: {data['translatedContent']}") # 避免输出过长
        else:
            print("Failed to save data")
            sys.exit(1)  # 新增：保存文件失败时，抛出异常终止工作流

    except Exception as e:
        print(f"Error in main process: {e}")
        sys.exit(1)  # 新增：发生任何未预期异常时，抛出异常终止工作流
    

if __name__ == "__main__":
    asyncio.run(main_async())
