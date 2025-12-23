"""
LeRobot Backend 부하 테스트

실행 방법:
    # 서버 실행 (다른 터미널)
    uvicorn lerobot.backend.app:app --host 0.0.0.0 --port 8000

    # Locust 실행
    cd tests/load
    locust -f locustfile.py --host http://localhost:8000

    # 웹 UI: http://localhost:8089

    # 헤드리스 모드 (CLI)
    locust -f locustfile.py --host http://localhost:8000 --headless -u 10 -r 2 -t 60s
"""

import json
import time
import random
from locust import HttpUser, task, between, events
from locust.exception import StopUser

# WebSocket 테스트용
try:
    from websockets.sync.client import connect as ws_connect
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("websockets 라이브러리 없음. pip install websockets")


class TelemetryUser(HttpUser):
    """텔레메트리 데이터 전송 시뮬레이션 (HTTP + WebSocket)"""
    wait_time = between(0.01, 0.05)  # 20~100 FPS 시뮬레이션

    def on_start(self):
        self.robot_id = f"robot_{random.randint(1, 100)}"
        self.frame_index = 0
        self.ws = None
        self._connect_ws()

    def _connect_ws(self):
        if not WS_AVAILABLE:
            return
        try:
            ws_url = f"ws://{self.host.replace('http://', '').replace('https://', '')}/ws/log/{self.robot_id}"
            self.ws = ws_connect(ws_url)
        except Exception as e:
            print(f"[WS] 연결 실패: {e}")

    def on_stop(self):
        if self.ws:
            try:
                self.ws.close()
            except:
                pass

    @task(10)
    def send_telemetry_ws(self):
        """WebSocket으로 텔레메트리 전송 (가장 빈번)"""
        if not self.ws:
            return

        frame_data = {
            "frame_index": self.frame_index,
            "timestamp": time.time(),
            "observation": {
                "joint_positions": [random.uniform(-3.14, 3.14) for _ in range(6)],
                "joint_velocities": [random.uniform(-1, 1) for _ in range(6)],
                "gripper": random.uniform(0, 1)
            },
            "action": {
                "joint_positions": [random.uniform(-3.14, 3.14) for _ in range(6)],
                "gripper": random.uniform(0, 1)
            }
        }

        start_time = time.time()
        try:
            self.ws.send(json.dumps(frame_data))
            elapsed = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="/ws/log/{robot_id}",
                response_time=elapsed,
                response_length=len(json.dumps(frame_data)),
                exception=None,
                context={}
            )
            self.frame_index += 1
        except Exception as e:
            events.request.fire(
                request_type="WebSocket",
                name="/ws/log/{robot_id}",
                response_time=0,
                response_length=0,
                exception=e,
                context={}
            )
            self._connect_ws()  # 재연결 시도

    @task(2)
    def get_health(self):
        """헬스체크"""
        self.client.get("/health")

    @task(1)
    def get_robots(self):
        """로봇 목록 조회"""
        self.client.get("/robots")

    @task(1)
    def get_sessions(self):
        """세션 목록 조회"""
        self.client.get("/sessions", params={"limit": 10})


class APIUser(HttpUser):
    """REST API 사용자 시뮬레이션 (대시보드/모니터링 클라이언트)"""
    wait_time = between(1, 3)

    def on_start(self):
        self.robot_ids = []
        self.session_ids = []
        self._fetch_initial_data()

    def _fetch_initial_data(self):
        try:
            resp = self.client.get("/robots")
            if resp.ok:
                data = resp.json()
                self.robot_ids = data.get("robots", [])
        except:
            pass

        try:
            resp = self.client.get("/sessions", params={"limit": 20})
            if resp.ok:
                data = resp.json()
                self.session_ids = [s["id"] for s in data.get("sessions", [])]
        except:
            pass

    @task(3)
    def get_health(self):
        """헬스체크"""
        self.client.get("/health")

    @task(2)
    def get_robots(self):
        """로봇 목록 조회"""
        self.client.get("/robots")

    @task(2)
    def get_sessions_list(self):
        """세션 목록 조회"""
        self.client.get("/sessions", params={
            "limit": random.choice([10, 20, 50]),
            "offset": random.randint(0, 100)
        })

    @task(1)
    def get_robot_status(self):
        """특정 로봇 상태 조회"""
        if self.robot_ids:
            robot_id = random.choice(self.robot_ids)
            self.client.get(f"/robots/{robot_id}/status")
        else:
            self.client.get("/robots/robot_1/status")

    @task(1)
    def get_session_detail(self):
        """세션 상세 조회"""
        if self.session_ids:
            session_id = random.choice(self.session_ids)
            self.client.get(f"/sessions/{session_id}")
        else:
            self.client.get("/sessions/1")


class MultiRobotUser(HttpUser):
    """멀티로봇 시나리오 테스트"""
    wait_time = between(0.016, 0.02)  # ~60 FPS

    def on_start(self):
        self.robot_id = f"multi_robot_{random.randint(1, 10)}"
        self.frame_index = 0
        self.ws = None
        self._connect_ws()

    def _connect_ws(self):
        if not WS_AVAILABLE:
            return
        try:
            ws_url = f"ws://{self.host.replace('http://', '').replace('https://', '')}/ws/log/{self.robot_id}"
            self.ws = ws_connect(ws_url)
        except Exception as e:
            print(f"[MultiRobot] WS 연결 실패: {e}")

    def on_stop(self):
        if self.ws:
            try:
                self.ws.close()
            except:
                pass

    @task
    def send_frame(self):
        """60FPS 프레임 전송 시뮬레이션"""
        if not self.ws:
            return

        frame_data = {
            "frame_index": self.frame_index,
            "timestamp": time.time(),
            "robot_id": self.robot_id,
            "observation": {
                "joint_positions": [random.uniform(-3.14, 3.14) for _ in range(6)],
                "ee_pos": [random.uniform(-1, 1) for _ in range(3)],
                "ee_quat": [random.uniform(-1, 1) for _ in range(4)],
            },
            "action": {
                "joint_positions": [random.uniform(-3.14, 3.14) for _ in range(6)],
            }
        }

        start_time = time.time()
        try:
            self.ws.send(json.dumps(frame_data))
            elapsed = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name=f"/ws/log/multi_robot",
                response_time=elapsed,
                response_length=len(json.dumps(frame_data)),
                exception=None,
                context={}
            )
            self.frame_index += 1
        except Exception as e:
            events.request.fire(
                request_type="WebSocket",
                name=f"/ws/log/multi_robot",
                response_time=0,
                response_length=0,
                exception=e,
                context={}
            )
            self._connect_ws()
