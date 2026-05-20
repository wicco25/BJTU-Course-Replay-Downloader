"""测试爬虫 - 验证API调用链"""
import json
from crawler import CourseCrawler


def main():
    c = CourseCrawler()

    # 1. 获取学期
    print("=" * 60)
    print("1. 获取学期列表")
    semesters = c.get_semesters()
    for s in semesters:
        flag = " <-- 当前" if s.get("currentFlag") == 2 else ""
        print(f"  {s['xqCode']} | {s['CNAME']}{flag}")

    # 找当前学期
    current = next((s for s in semesters if s.get("currentFlag") == 2), None)
    if not current and semesters:
        current = semesters[0]
    if not current:
        print("没有可用学期")
        return

    xq_code = current["xqCode"]
    print(f"\n使用学期: {current['CNAME']} ({xq_code})")

    # 2. 获取课程列表
    print("\n" + "=" * 60)
    print("2. 获取课程列表")
    courses = c.get_all_courses(xq_code)
    print(f"共 {len(courses)} 门课程")
    for co in courses[:5]:
        print(f"  [{co['id']}] {co['name']} | {co['course_num']} | "
              f"教师: {co.get('teacher_name','')} | fz_id: {co['fz_id']}")

    if not courses:
        print("没有课程数据")
        return

    # 选第一门课
    course = courses[0]
    course_num = course["course_num"]
    course_id = course["id"]
    teacher_id = str(course.get("teacher_id", ""))

    print(f"\n选择课程: {course['name']}")

    # 3. 获取教学日历（回放列表）
    print("\n" + "=" * 60)
    print("3. 获取教学日历（回放列表）")
    calendar = c.get_teaching_calendar(course_id)
    print(f"课次数: {len(calendar)}")
    import re
    def parse_params(p):
        if isinstance(p, dict):
            return p
        if isinstance(p, str):
            return dict(re.findall(r'(\w+)=([^}]+)', p))
        return {}

    for cal in calendar[:5]:
        params = parse_params(cal.get("params", ""))
        vid = params.get("videoId", "N/A")
        print(f"  [{cal['id']}] {cal.get('courseScheName','')} | "
              f"{cal.get('courseBetween','')} | videoId={vid}")

    # 找一个有videoId的课次
    with_video = [cal for cal in calendar
                  if parse_params(cal.get("params", "")).get("videoId")]
    if not with_video:
        print("没有找到有回放视频的课次")
        return

    sched = with_video[0]
    sched_id = sched["id"]
    params = parse_params(sched.get("params", ""))
    rp_id = params["videoId"]
    print(f"\n选择课次: {sched['courseScheName']} (schedId={sched_id}, rpId={rp_id})")

    # 4. 获取视频流信息
    print("\n" + "=" * 60)
    print("4. 获取视频流URL")
    stream = c.get_stream_info(sched_id, user_level=1, user_id="170179")
    if stream:
        urls = c.build_stream_urls(stream)
        print(f"可用视频流: {len(urls)} 个")
        for u in urls:
            print(f"  [{u['label']}] {u['url'][:100]}...")
        course_sched = stream.get("course_sched", {})
        print(f"  课程节次: {course_sched.get('courseBetween', '')}")
        print(f"  教室: {course_sched.get('classRoom', '')}")
    else:
        print("未获取到视频流信息（可能该课次无回放或无权限）")

    # 5. 尝试获取字幕
    print("\n" + "=" * 60)
    print("5. 获取字幕(VTT)")
    subtitle = c.get_subtitle(rp_id)
    if subtitle:
        lines = subtitle.strip().split("\n")
        print(f"字幕行数: {len(lines)}")
        # 显示前几行非空内容
        texts = [l for l in lines if l.strip() and not l.strip().startswith(("WEBVTT", "00:", "NOTE"))]
        for t in texts[:5]:
            print(f"  {t[:100]}")
    else:
        print("未获取到字幕（可能该视频无字幕）")


if __name__ == "__main__":
    main()
