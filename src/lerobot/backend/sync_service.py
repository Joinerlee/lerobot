"""
LeRobot Sync Service (Sidecar 동기화 서비스)
===========================================

이 스크립트는 로컬에서 생성된 LeRobot 데이터셋을 백엔드 서버로 자동 업로드합니다.
로봇 PC에서 백그라운드로 실행하면, 새로운 데이터가 생길 때마다 서버로 백업됩니다.

사용법:
    python sync_service.py

환경변수:
    LEROBOT_OUTPUT_DIR: LeRobot 데이터셋 저장 경로 (기본: outputs/train)
    LEROBOT_BACKEND_URL: 백엔드 서버 URL (기본: http://localhost:8000)
"""

import time
import requests
import os
import glob
from pathlib import Path

# =============================================================================
# 설정 (환경변수로 오버라이드 가능)
# =============================================================================
LEROBOT_OUTPUT_DIR = os.getenv(
    "LEROBOT_OUTPUT_DIR",
    "/home/nsm_industry_technology_team/Desktop/NSM_Lerobot/outputs/train"
)
BACKEND_URL = os.getenv("LEROBOT_BACKEND_URL", "http://localhost:8000")


# =============================================================================
# 메인 로직
# =============================================================================

def find_new_episodes():
    """
    아직 업로드되지 않은 새로운 에피소드(데이터셋)를 찾아 업로드합니다.

    LeRobot 데이터셋 구조:
    - {root}/{repo_id}/data/chunk-{i}.parquet  (관절 데이터)
    - {root}/{repo_id}/videos/{camera}/{episode}.mp4  (영상 데이터)
    """
    datasets = glob.glob(os.path.join(LEROBOT_OUTPUT_DIR, "*"))

    for ds_path in datasets:
        if not os.path.isdir(ds_path):
            continue

        # 1. 비디오 파일 찾기 및 업로드
        video_dir = os.path.join(ds_path, "videos")
        if os.path.exists(video_dir):
            videos = glob.glob(os.path.join(video_dir, "**/*.mp4"), recursive=True)
            for vid in videos:
                if not is_uploaded(vid):
                    print(f"[Sync] 새 비디오 발견: {vid}")
                    upload_video(ds_path, vid)

        # 2. Parquet 파일 찾기 및 업로드
        parquet_files = glob.glob(os.path.join(ds_path, "data", "*.parquet"))
        for pq in parquet_files:
            if not is_uploaded(pq):
                print(f"[Sync] 새 데이터셋 청크 발견: {pq}")
                upload_dataset_chunk(ds_path, pq)


def is_uploaded(file_path: str) -> bool:
    """파일이 이미 업로드되었는지 확인합니다 (.uploaded 마커 파일 체크)."""
    return os.path.exists(file_path + ".uploaded")


def mark_as_uploaded(file_path: str):
    """파일을 업로드 완료로 표시합니다 (.uploaded 마커 파일 생성)."""
    with open(file_path + ".uploaded", "w") as f:
        f.write("uploaded")


def upload_dataset_chunk(root_dir: str, parquet_path: str):
    """Parquet 데이터셋 청크를 백엔드로 업로드합니다."""
    dataset_name = os.path.basename(root_dir)
    relative_path = os.path.relpath(parquet_path, root_dir)

    print(f"[Sync] Parquet 업로드 중: {relative_path}")
    if upload_to_backend(dataset_name, relative_path, parquet_path):
        mark_as_uploaded(parquet_path)


def upload_video(root_dir: str, video_path: str):
    """비디오 파일을 백엔드로 업로드합니다."""
    dataset_name = os.path.basename(root_dir)
    relative_path = os.path.relpath(video_path, root_dir)

    print(f"[Sync] 비디오 업로드 중: {relative_path}")
    if upload_to_backend(dataset_name, relative_path, video_path):
        mark_as_uploaded(video_path)


def upload_to_backend(dataset_name: str, relative_path: str, file_path: str) -> bool:
    """
    파일을 백엔드 서버로 업로드합니다.

    Args:
        dataset_name: 데이터셋 이름 (폴더명)
        relative_path: 데이터셋 내 상대 경로
        file_path: 실제 파일 경로

    Returns:
        업로드 성공 여부
    """
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
                print(f" -> 성공: {relative_path}")
                return True
            else:
                print(f" -> 실패: {response.text}")
                return False
    except Exception as e:
        print(f" -> 에러: {e}")
        return False


# =============================================================================
# 엔트리포인트
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("LeRobot Sync Service 시작")
    print("=" * 50)
    print(f"감시 경로: {LEROBOT_OUTPUT_DIR}")
    print(f"백엔드 서버: {BACKEND_URL}")
    print("=" * 50)
    print("새 파일을 감지하면 자동으로 업로드합니다...")
    print("종료하려면 Ctrl+C를 누르세요.\n")

    while True:
        find_new_episodes()
        time.sleep(5)  # 5초마다 스캔
