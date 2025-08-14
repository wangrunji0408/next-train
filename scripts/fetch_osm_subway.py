#!/usr/bin/env python3
"""
从OpenStreetMap获取北京地铁站点GPS坐标数据

使用Overpass API查询OpenStreetMap数据库中的地铁站点信息
"""

import requests
import json
import re


def clean_station_name(name):
    """清理站点名称，去掉括号及其中内容"""
    if not name:
        return name
    # 去掉括号及其中内容
    cleaned = re.sub(r"\([^)]*\)", "", name)
    # 去掉其他可能的括号类型
    cleaned = re.sub(r"（[^）]*）", "", cleaned)
    # 去掉首尾空格
    return cleaned.strip()


def clean_line_name(name: str) -> str:
    """清理线路名称，使用通用规则提取线路名称"""
    if not name:
        return name

    space_match = re.search(r"\s+(.+?)号?线", name)
    if space_match:
        return space_match.group(1)


def fetch_beijing_subway_from_osm():
    """从OpenStreetMap获取北京地铁站点数据"""

    # Overpass API endpoint
    overpass_url = "https://overpass-api.de/api/interpreter"

    # 查询所有北京地区的地铁站点
    # 使用边界框限定北京地区：纬度39.5-40.5，经度116.0-117.0
    overpass_query = """
    [out:json][timeout:30][bbox:39.5,116.0,40.5,117.0];
    (
      node["railway"="station"]["station"="subway"];
      node["public_transport"="stop_position"]["subway"="yes"];
      node["railway"="station"]["network"~"北京|Beijing"];
    );
    out body;
    """

    try:
        response = requests.get(overpass_url, params={"data": overpass_query})
        response.raise_for_status()
        data = response.json()

        stations = {}

        for element in data.get("elements", []):
            if element.get("type") == "node":
                tags = element.get("tags", {})
                station_name = tags.get("name") or tags.get("name:zh")

                if station_name:
                    lat = element.get("lat")
                    lon = element.get("lon")

                    if lat and lon:
                        # 清理站点名称
                        cleaned_name = clean_station_name(station_name)
                        if cleaned_name and cleaned_name not in stations:
                            stations[cleaned_name] = [lat, lon]
                            print(f"找到站点: {cleaned_name} ({lat}, {lon})")

        return stations

    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return {}
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return {}


def fetch_subway_lines_from_osm():
    """获取北京地铁线路信息"""

    overpass_url = "https://overpass-api.de/api/interpreter"

    # 查询地铁线路
    overpass_query = """
    [out:json][timeout:30];
    (
      relation["type"="route"]["route"="subway"]["network"~"北京|Beijing"];
    );
    out body;
    """

    try:
        response = requests.get(overpass_url, params={"data": overpass_query})
        response.raise_for_status()
        data = response.json()

        lines = []
        seen_lines = set()

        for element in data.get("elements", []):
            if element.get("type") == "relation":
                tags = element.get("tags", {})
                line_name = tags.get("name") or tags.get("ref")
                line_color = tags.get("colour")

                if line_name:
                    # 清理线路名称
                    cleaned_name = clean_line_name(line_name)
                    if cleaned_name and cleaned_name not in seen_lines:
                        line_info = {"lineName": cleaned_name, "lineColor": line_color}
                        lines.append(line_info)
                        seen_lines.add(cleaned_name)
                        print(
                            f"找到线路: {cleaned_name} (原名: {line_name}, 颜色: {line_color})"
                        )
        lines.sort(key=lambda x: x["lineName"])  # 按线路名称排序
        return lines

    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return []


def main():
    """主函数"""
    print("从OpenStreetMap获取北京地铁数据...")

    # 获取地铁站点
    print("\n=== 获取地铁站点 ===")
    stations = fetch_beijing_subway_from_osm()

    # 获取地铁线路
    print("\n=== 获取地铁线路 ===")
    lines = fetch_subway_lines_from_osm()

    # 组织数据格式
    osm_data = {"lines": lines, "coordinates": stations}

    # 保存到文件
    output_file = "routes.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(osm_data, f, ensure_ascii=False, indent=2)
        print(f"\n数据已保存到: {output_file}")
        print(f"共获取到 {len(stations)} 个站点，{len(lines)} 条线路")
    except Exception as e:
        print(f"保存文件失败: {e}")


if __name__ == "__main__":
    main()
