import time
import requests
import os
import glob
from pathlib import Path

# 설정 (환경변수로 오버라이드 가능)
LEROBOT_OUTPUT_DIR = os.getenv(
    "LEROBOT_OUTPUT_DIR",
    "/home/nsm_industry_technology_team/Desktop/NSM_Lerobot/outputs/train"
)
BACKEND_URL = os.getenv("LEROBOT_BACKEND_URL", "http://localhost:8000")


def find_new_episodes():
    """Run locally to find episodes that are not yet uploaded."""
    # LeRobot 구조: outputs/train/{dataset_name}/episodes/episode_{id}
    # 우리는 단순화를 위해 outputs/train 하위의 모든 .parquet 파일을 찾습니다.
    # 실제로는 'processed' 마커 파일을 두어 중복 업로드를 방지해야 합니다.

    datasets = glob.glob(os.path.join(LEROBOT_OUTPUT_DIR, "*"))
    for ds_path in datasets:
        if not os.path.isdir(ds_path):
            continue

        # LeRobotDataset 저장 방식:
        # {root}/{repo_id}/data/chunk-{i}.parquet
        # {root}/{repo_id}/videos/{camera}/{episode}.mp4

        # 1. 비디오 파일 찾기 및 업로드
        video_dir = os.path.join(ds_path, "videos")
        if os.path.exists(video_dir):
            videos = glob.glob(os.path.join(video_dir, "**/*.mp4"), recursive=True)
            for vid in videos:
                if not is_uploaded(vid):
                    print(f"[Sync] New video found: {vid}")
                    upload_video(ds_path, vid)

        # 2. Parquet 파일 찾기 및 업로드
        parquet_files = glob.glob(os.path.join(ds_path, "data", "*.parquet"))
        for pq in parquet_files:
            if not is_uploaded(pq):
                print(f"[Sync] New dataset chunk found: {pq}")
                upload_dataset_chunk(ds_path, pq)

def is_uploaded(file_path):
    return os.path.exists(file_path + ".uploaded")

def mark_as_uploaded(file_path):
    with open(file_path + ".uploaded", "w") as f:
        f.write("uploaded")

def upload_dataset_chunk(root_dir, parquet_path):
    dataset_name = os.path.basename(root_dir)
    relative_path = os.path.relpath(parquet_path, root_dir)
    
    print(f"[Sync] Uploading Parquet: {relative_path}")
    if upload_to_backend(dataset_name, relative_path, parquet_path):
        mark_as_uploaded(parquet_path)

def upload_video(root_dir, video_path):
    dataset_name = os.path.basename(root_dir)
    relative_path = os.path.relpath(video_path, root_dir)
    
    print(f"[Sync] Uploading Video: {relative_path}")
    if upload_to_backend(dataset_name, relative_path, video_path):
        mark_as_uploaded(video_path)

def upload_to_backend(dataset_name, relative_path, file_path):
    url = f"{BACKEND_URL}/upload/sync"
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {
                'dataset_name': dataset_name,
                'relative_path': relative_path
            }
            response = requests.post(url, files=files, data=data)
            
            if response.status_code == 200:
                print(f" -> Success: {relative_path}")
                return True
            else:
                print(f" -> Failed: {response.text}")
                return False
    except Exception as e:
        print(f" -> Error: {e}")
        return False

if __name__ == "__main__":
    print(f"Starting LeRobot Sync Service...")
    print(f"Watching: {LEROBOT_OUTPUT_DIR}")
    print(f"Target Backend: {BACKEND_URL}")
    
    while True:
        find_new_episodes()
        time.sleep(5) # 5초마다 스캔
