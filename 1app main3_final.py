"""
창고 정리 앱 - 기반 구조
화면 흐름: 창고 선택 → 사진 촬영 → 창고 정리
"""

import os
import threading
import urllib.request

import json as _json

# ─── 내장 JSON 데이터 ───
_loaded_json = None  # 업로드된 JSON 데이터 저장


from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.camera import Camera
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line, Triangle


import math as _math

def _hex_to_rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16)/255.0 for i in (0, 2, 4))


class Viewer3DWidget(Widget):
    """순수 Kivy Canvas로 3D 박스 렌더링 (드래그 회전)"""

    def __init__(self, packing_data, **kwargs):
        super().__init__(**kwargs)
        self.data = packing_data
        self.rot_x = 25.0
        self.rot_y = -35.0
        self.scale = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._touches = []
        self._pinch_dist = None
        self._last_tap_time = 0
        self.bind(size=self._redraw, pos=self._redraw)
        self._redraw()

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        self._touches.append(touch)

        # 마우스 휠 줌
        if touch.is_mouse_scrolling:
            if touch.button == 'scrollup':
                self.scale = max(0.2, self.scale - 0.1)
            elif touch.button == 'scrolldown':
                self.scale = min(8.0, self.scale + 0.1)
            self._redraw()
            return True

        # 더블탭 → 리셋
        import time
        now = time.time()
        if now - self._last_tap_time < 0.3:
            self.rot_x = 25.0; self.rot_y = -35.0
            self.scale = 1.0; self.pan_x = 0.0; self.pan_y = 0.0
            self._redraw()
        self._last_tap_time = now

        # 핀치 시작 거리 기록
        if len(self._touches) == 2:
            t1, t2 = self._touches
            dx = t1.x - t2.x; dy = t1.y - t2.y
            self._pinch_dist = _math.sqrt(dx*dx + dy*dy)

        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False

        if len(self._touches) == 2:
            # 두 손가락: 핀치 줌
            t1, t2 = self._touches
            dx = t1.x - t2.x; dy = t1.y - t2.y
            dist = _math.sqrt(dx*dx + dy*dy)
            if self._pinch_dist and self._pinch_dist > 0:
                self.scale = max(0.2, min(8.0, self.scale * (dist / self._pinch_dist)))
            self._pinch_dist = dist
        else:
            # 한 손가락: 회전
            self.rot_y += touch.dx * 0.4
            self.rot_x -= touch.dy * 0.4

        self._redraw()
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
        if touch in self._touches:
            self._touches.remove(touch)
        self._pinch_dist = None
        return False

    def _rotate(self, x, y, z):
        rx = _math.radians(self.rot_x)
        ry = _math.radians(self.rot_y)
        cy, sy = _math.cos(ry), _math.sin(ry)
        cx, sx = _math.cos(rx), _math.sin(rx)
        nx =  cy*x + sy*sx*y + sy*cx*z
        ny =       +    cx*y -    sx*z
        nz = -sy*x + cy*sx*y + cy*cx*z
        return nx, ny, nz

    def _to_screen(self, x, y, z, cx, cy, scale, fov=700):
        rx, ry, rz = self._rotate(x, y, z)
        d = fov / (fov + rz + 300)
        sx = cx + rx * scale * d + self.pan_x
        sy = cy + ry * scale * d + self.pan_y
        return sx, sy, rz

    def _redraw(self, *args):
        self.canvas.clear()
        d = self.data
        cont = d['container']
        items = d['items']
        W, H, D = cont['width'], cont['height'], cont['depth']
        cw, ch = self.width, self.height
        if cw < 1 or ch < 1:
            return

        # ── 스케일: 회전 후 최대 대각선 길이 기준으로 여백 포함 계산 ──
        diag = _math.sqrt(W*W + H*H + D*D)
        sc = min(cw, ch) / diag * 0.55 * self.scale

        # 화면 중심 (pan 포함)
        cx = cw / 2 + self.pan_x
        cy = ch / 2 + self.pan_y

        # 컨테이너 중심을 원점으로 맞춤
        ox, oy, oz = W / 2, H / 2, D / 2

        def pt(x, y, z):
            """월드 좌표 → 화면 좌표 (원근 투영)"""
            rx, ry, rz = self._rotate(x - ox, y - oy, z - oz)
            fov = 900
            d_proj = fov / (fov + rz + diag * 2)
            sx = cx + rx * sc * d_proj
            sy = cy + ry * sc * d_proj
            return sx, sy, rz

        def apply_rotation(size, rotation_type):
            w,h,d = size['width'],size['height'],size['depth']
            if   rotation_type == 1: return h, w, d
            elif rotation_type == 2: return d, h, w
            elif rotation_type == 3: return h, d, w
            elif rotation_type == 4: return d, w, h
            elif rotation_type == 5: return w, d, h
            return w, h, d

        def clamp(v, lo, hi):
            return max(lo, min(hi, v))

        def corners(pos, size, rotation_type=0):
            x0,y0,z0 = pos['x'], pos['y'], pos['z']
            dx,dy,dz = apply_rotation(size, rotation_type)
            x1=clamp(x0,0,W);    y1=clamp(y0,0,H);    z1=clamp(z0,0,D)
            x2=clamp(x0+dx,0,W); y2=clamp(y0+dy,0,H); z2=clamp(z0+dz,0,D)
            return [
                pt(x1, y1, z1), pt(x2, y1, z1),
                pt(x2, y2, z1), pt(x1, y2, z1),
                pt(x1, y1, z2), pt(x2, y1, z2),
                pt(x2, y2, z2), pt(x1, y2, z2),
            ]

        EDGES = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        FACES = [(0,1,2,3),(4,7,6,5),(0,4,5,1),(2,6,7,3),(0,3,7,4),(1,5,6,2)]

        with self.canvas:
            # 배경
            Color(0.08, 0.08, 0.12, 1)
            Rectangle(pos=self.pos, size=self.size)

            # 컨테이너 외곽선
            Color(1, 1, 1, 0.5)
            cp = corners({'x':0,'y':0,'z':0}, {'width':W,'height':H,'depth':D}, 0)
            for a, b in EDGES:
                Line(points=[cp[a][0], cp[a][1], cp[b][0], cp[b][1]], width=1.5)

            # 깊이 정렬 (뒤→앞)
            def avg_depth(item):
                p = item['position']; s = item['size']
                dx,dy,dz = apply_rotation(s, item.get('rotation_type',0))
                cx2 = clamp(p['x']+dx/2, 0, W)
                cy2 = clamp(p['y']+dy/2, 0, H)
                cz2 = clamp(p['z']+dz/2, 0, D)
                _, _, rz = self._rotate(cx2-ox, cy2-oy, cz2-oz)
                return rz

            for item in sorted(items, key=avg_depth):
                r, g, b = _hex_to_rgb(item['color'])
                pts = corners(item['position'], item['size'], item.get('rotation_type', 0))

                # 반투명 면
                Color(r, g, b, 0.38)
                for face in FACES:
                    p0,p1,p2,p3 = [pts[i] for i in face]
                    Triangle(points=[p0[0],p0[1], p1[0],p1[1], p2[0],p2[1]])
                    Triangle(points=[p0[0],p0[1], p2[0],p2[1], p3[0],p3[1]])

                # 외곽선
                Color(r, g, b, 1.0)
                for a, b_i in EDGES:
                    Line(points=[pts[a][0],pts[a][1], pts[b_i][0],pts[b_i][1]], width=1.0)

                # ID 라벨
                p = item['position']; s = item['size']
                lx, ly, _ = pt(p['x']+s['width']/2, p['y']+s['height']/2, p['z']+s['depth']/2)
                from kivy.core.text import Label as CoreLabel
                lbl = CoreLabel(text=item['id'], font_size=dp(9))
                lbl.refresh()
                tex = lbl.texture
                if tex:
                    Color(0, 0, 0, 0.55)
                    Rectangle(pos=(lx-tex.width/2-2, ly-tex.height/2-2),
                              size=(tex.width+4, tex.height+4))
                    Color(1, 1, 1, 1)
                    Rectangle(texture=tex, pos=(lx-tex.width/2, ly-tex.height/2), size=tex.size)


class Viewer3DScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._built = False

    def on_enter(self):
        # JSON이 새로 로드됐을 수 있으므로 매번 뷰어 재생성
        self.clear_widgets()
        self._built = False
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation='vertical')

        # 상단 바
        top = BoxLayout(orientation='horizontal',
                        size_hint=(1, None), height=dp(48),
                        padding=dp(6), spacing=dp(8))
        with top.canvas.before:
            Color(0.1, 0.1, 0.18, 1)
            _bg = Rectangle(pos=top.pos, size=top.size)
            top.bind(pos=lambda w,v: setattr(_bg,'pos',v),
                     size=lambda w,v: setattr(_bg,'size',v))

        btn_back = KButton(text='< Back', size_hint=(None,1), width=dp(80),
                           font_size=dp(13), background_normal='',
                           background_color=(0.2,0.2,0.28,1), color=(0.8,0.8,0.9,1))
        btn_back.bind(on_release=lambda x: self._go_back())

        data = _loaded_json
        if data is None:
            # JSON 미로드 상태
            top.add_widget(KLabel(
                text='No JSON loaded. Use "Load JSON" in camera screen.',
                font_size=dp(11), color=(1,0.4,0.4,1), size_hint=(1,1), halign='center'))
            root.add_widget(top)
            no_data_lbl = KLabel(
                text='Please load a packing_result JSON file first.',
                font_size=dp(14), color=(0.7,0.7,0.8,1), halign='center')
            root.add_widget(no_data_lbl)
            self.add_widget(root)
            return

        st = data['statistics']
        c  = data['container']
        info = KLabel(
            text=f"Vol: {st['volume_utilization_percent']}%  |  Weight: {c['total_weight']}/{c['max_weight']}  |  Drag:rotate  Pinch:zoom  2x:reset",
            font_size=dp(11), color=(0.7,0.9,1,1), size_hint=(1,1), halign='center')

        top.add_widget(btn_back)
        top.add_widget(info)

        self.viewer = Viewer3DWidget(packing_data=data, size_hint=(1,1))

        root.add_widget(top)
        root.add_widget(self.viewer)
        self.add_widget(root)

    def _go_back(self):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'organize'


# 앱 배경색 (다크 테마)
Window.clearcolor = (0.08, 0.08, 0.12, 1)

# ─────────────────────────────────────────────
# 한글 폰트 설정 (Noto Sans KR 자동 다운로드)
# ─────────────────────────────────────────────
FONT_URL = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf"
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NotoSansKR.otf")

_font_ready = False


def _download_font_thread(on_done):
    """백그라운드에서 폰트 다운로드"""
    try:
        if not os.path.exists(FONT_PATH):
            print("[폰트] 다운로드 중...")
            urllib.request.urlretrieve(FONT_URL, FONT_PATH)
            print("[폰트] 다운로드 완료!")
        else:
            print("[폰트] 이미 존재함, 스킵")
        Clock.schedule_once(lambda dt: on_done(True), 0)
    except Exception as e:
        print(f"[폰트] 다운로드 실패: {e}")
        Clock.schedule_once(lambda dt: on_done(False), 0)


def register_font():
    """폰트 등록"""
    if os.path.exists(FONT_PATH):
        LabelBase.register(name='NotoKR', fn_regular=FONT_PATH)
        return True
    return False


# ─────────────────────────────────────────────
# 로딩 화면 (폰트 다운로드 중 표시)
# ─────────────────────────────────────────────
class LoadingScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = BoxLayout(orientation='vertical', padding=dp(40), spacing=dp(20))

        layout.add_widget(Label(size_hint=(1, 0.3)))

        self.icon_label = Label(
            text='[BOX]',
            font_size=dp(64),
            size_hint=(1, 0.2),
        )
        layout.add_widget(self.icon_label)

        self.status_label = Label(
            text='Downloading font...\n(First run only)',
            font_size=dp(16),
            color=(0.8, 0.8, 0.9, 1),
            halign='center',
            size_hint=(1, 0.2),
        )
        layout.add_widget(self.status_label)

        self.progress_label = Label(
            text='Please wait...',
            font_size=dp(13),
            color=(0.5, 0.6, 0.8, 1),
            halign='center',
            size_hint=(1, 0.1),
        )
        layout.add_widget(self.progress_label)

        layout.add_widget(Label(size_hint=(1, 0.2)))

        self.add_widget(layout)

    def on_enter(self):
        threading.Thread(
            target=_download_font_thread,
            args=(self._on_font_done,),
            daemon=True
        ).start()

    def _on_font_done(self, success):
        global _font_ready
        if success and register_font():
            _font_ready = True
            self.status_label.text = 'Ready!'
            self.progress_label.text = 'Starting app...'
            Clock.schedule_once(self._go_next, 0.8)
        else:
            # 폰트 다운로드 실패해도 앱은 실행 (한글 깨질 수 있음)
            self.status_label.text = 'Font download failed\n(Check internet connection)'
            self.progress_label.text = 'Continuing with default font...'
            Clock.schedule_once(self._go_next, 1.5)

    def _go_next(self, dt):
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'select'


# ─────────────────────────────────────────────
# 공통 헬퍼: 폰트 적용된 Label/Button 생성
# ─────────────────────────────────────────────
def KLabel(**kwargs):
    if _font_ready:
        kwargs.setdefault('font_name', 'NotoKR')
    return Label(**kwargs)


def KButton(**kwargs):
    btn = Button(**kwargs)
    if _font_ready:
        btn.font_name = 'NotoKR'
    return btn


# ─────────────────────────────────────────────
# 1화면: 창고 형태 선택
# ─────────────────────────────────────────────
class SelectWarehouseScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._built = False

    def on_enter(self):
        # 폰트 준비 후 진입할 때 UI 빌드
        if not self._built:
            self._built = True
            self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation='vertical', padding=dp(30), spacing=dp(20))

        title = KLabel(
            text='Warehouse App',
            font_size=dp(32),
            bold=True,
            color=(1, 1, 1, 1),
            size_hint=(1, 0.15),
        )
        subtitle = KLabel(
            text='창고 형태를 선택해주세요',
            font_size=dp(16),
            color=(0.7, 0.7, 0.8, 1),
            size_hint=(1, 0.08),
        )

        root.add_widget(title)
        root.add_widget(subtitle)

        btn_area = GridLayout(cols=2, spacing=dp(15), size_hint=(1, 0.6))

        btn_a = self._make_warehouse_btn('A', '일반 창고\n[color=000000]Click Here[/color]', '[A]', (0.2, 0.5, 1, 1))
        btn_a.bind(on_release=lambda x: self.select_warehouse('A'))
        btn_area.add_widget(btn_a)

        for label in ['B', 'C', 'D']:
            btn = self._make_warehouse_btn(label, '준비 중', 'X', (0.3, 0.3, 0.35, 1), disabled=True)
            btn_area.add_widget(btn)

        root.add_widget(btn_area)
        root.add_widget(Label(size_hint=(1, 0.17)))

        self.add_widget(root)

    def _make_warehouse_btn(self, key, name, icon, color, disabled=False):
        btn = KButton(
            text=f'{icon}\n[b]{key}[/b]\n{name}',
            markup=True,
            font_size=dp(15),
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 0.4) if disabled else (1, 1, 1, 1),
            disabled=disabled,
            size_hint=(1, 1),
            halign='center',
        )
        with btn.canvas.before:
            Color(*color, 0.25 if disabled else 0.85)
            btn._bg = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[dp(16)])
        btn.bind(pos=lambda w, v: setattr(w._bg, 'pos', v))
        btn.bind(size=lambda w, v: setattr(w._bg, 'size', v))
        return btn

    def select_warehouse(self, warehouse_type):
        app = App.get_running_app()
        app.selected_warehouse = warehouse_type
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'camera'


# ─────────────────────────────────────────────
# 2화면: 사진 촬영
# ─────────────────────────────────────────────
class CameraScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.photos = []
        self._built = False

    def on_enter(self):
        if not self._built:
            self._built = True
            self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10))

        self.guide_label = KLabel(
            text='Take photos of items\nto store in warehouse',
            font_size=dp(18),
            bold=True,
            color=(1, 1, 1, 1),
            halign='center',
            size_hint=(1, 0.12),
        )
        root.add_widget(self.guide_label)

        try:
            self.camera = Camera(index=0, resolution=(640, 480), play=True, size_hint=(1, 0.55))
            # 카메라 뷰 90도 시계방향 회전 보정
            with self.camera.canvas.before:
                from kivy.graphics import PushMatrix, Rotate
                PushMatrix()
                self._cam_rot = Rotate(angle=-90, origin=self.camera.center)
                self.camera.bind(center=lambda w, v: setattr(self._cam_rot, 'origin', v))
            with self.camera.canvas.after:
                from kivy.graphics import PopMatrix
                PopMatrix()
            root.add_widget(self.camera)
            self.camera_available = True
        except Exception:
            placeholder = KLabel(
                text='Camera\nLoading...',
                font_size=dp(24),
                color=(0.5, 0.5, 0.6, 1),
                halign='center',
                size_hint=(1, 0.55),
            )
            root.add_widget(placeholder)
            self.camera_available = False

        self.count_label = KLabel(
            text='Photos taken: 0  |  JSON: not loaded',
            font_size=dp(14),
            color=(0.6, 0.9, 0.6, 1),
            size_hint=(1, 0.07),
        )
        root.add_widget(self.count_label)

        # 찍은 사진 썸네일 가로 스크롤
        self.photo_scroll = ScrollView(
            size_hint=(1, 0.15),
            do_scroll_x=True,
            do_scroll_y=False,
        )
        self.photo_strip = BoxLayout(
            orientation='horizontal',
            spacing=dp(6),
            size_hint_x=None,
            width=dp(6),
            padding=[dp(6), dp(3)],
        )
        with self.photo_strip.canvas.before:
            Color(0.1, 0.1, 0.15, 1)
            _bg = Rectangle(pos=self.photo_strip.pos, size=self.photo_strip.size)
            self.photo_strip.bind(
                pos=lambda w,v: setattr(_bg,'pos',v),
                size=lambda w,v: setattr(_bg,'size',v),
            )
        self.photo_scroll.add_widget(self.photo_strip)
        root.add_widget(self.photo_scroll)

        btn_row = BoxLayout(orientation='horizontal', spacing=dp(12), size_hint=(1, 0.13))

        btn_capture = KButton(
            text='Capture',
            font_size=dp(16),
            bold=True,
            background_normal='',
            background_color=(0.2, 0.6, 1, 1),
            size_hint=(0.34, 1),
        )
        btn_capture.bind(on_release=self.capture_photo)

        btn_json = KButton(
            text='Load JSON',
            font_size=dp(14),
            bold=True,
            background_normal='',
            background_color=(0.8, 0.5, 0.1, 1),
            size_hint=(0.33, 1),
        )
        btn_json.bind(on_release=self.pick_json)

        btn_next = KButton(
            text='Next >',
            font_size=dp(16),
            bold=True,
            background_normal='',
            background_color=(0.15, 0.75, 0.4, 1),
            size_hint=(0.33, 1),
        )
        btn_next.bind(on_release=self.go_next)

        btn_row.add_widget(btn_capture)
        btn_row.add_widget(btn_json)
        btn_row.add_widget(btn_next)
        root.add_widget(btn_row)

        btn_back = KButton(
            text='< Back',
            font_size=dp(13),
            background_normal='',
            background_color=(0.2, 0.2, 0.25, 1),
            color=(0.7, 0.7, 0.8, 1),
            size_hint=(1, 0.08),
        )
        btn_back.bind(on_release=self.go_back)
        root.add_widget(btn_back)

        self.add_widget(root)

    def capture_photo(self, *args):
        if self.camera_available:
            filename = f'photo_{len(self.photos)+1}.png'
            self.camera.export_to_png(filename)
            self._rotate_image(filename, 90)
            self.photos.append(filename)
            self._add_thumbnail(filename)
        else:
            self.photos.append(f'dummy_photo_{len(self.photos)+1}.png')
        self._update_label()

    def _add_thumbnail(self, filepath):
        """촬영 후 썸네일을 스크롤뷰에 추가"""
        from kivy.uix.image import Image as KvImage
        from kivy.uix.behaviors import ButtonBehavior

        class ThumbBtn(ButtonBehavior, KvImage):
            pass

        thumb_size = dp(90)
        idx = len(self.photos) - 1

        thumb = ThumbBtn(
            source=filepath,
            size_hint=(None, None),
            size=(thumb_size, thumb_size),
        )
        # 탭하면 상세 화면으로
        thumb.bind(on_release=lambda w: self._open_detail(idx))
        self.photo_strip.add_widget(thumb)
        self.photo_strip.width = len(self.photo_strip.children) * (thumb_size + dp(6)) + dp(6)
        Clock.schedule_once(lambda dt: setattr(self.photo_scroll, 'scroll_x', 1), 0.1)

    def _open_detail(self, idx):
        detail = self.manager.get_screen('photo_detail')
        detail.load(self.photos[idx], idx)
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'photo_detail'

    def _rotate_image(self, filepath, angle):
        """저장된 PNG를 회전 보정"""
        try:
            # Pillow 사용
            from PIL import Image as PILImage
            img = PILImage.open(filepath)
            img = img.rotate(-angle, expand=True)  # 시계방향 = 음수
            img.save(filepath)
        except ImportError:
            try:
                # Pillow 없으면 kivy texture로 회전
                from kivy.core.image import Image as CoreImage
                import struct, zlib

                # PNG 파일을 텍스처로 읽어서 회전
                tex = CoreImage(filepath).texture
                w, h = tex.size
                pixels = tex.pixels  # RGBA bytes

                # 90도 시계방향 회전: (x,y) → (h-1-y, x)
                new_pixels = bytearray(len(pixels))
                for y in range(h):
                    for x in range(w):
                        src = (y * w + x) * 4
                        # 회전 후 좌표
                        nx = h - 1 - y
                        ny = x
                        dst = (ny * h + nx) * 4
                        new_pixels[dst:dst+4] = pixels[src:src+4]

                # 회전된 텍스처 저장
                from kivy.graphics.texture import Texture
                new_tex = Texture.create(size=(h, w), colorfmt='rgba')
                new_tex.blit_buffer(bytes(new_pixels), colorfmt='rgba', bufferfmt='ubyte')
                new_tex.save(filepath)
            except Exception as e:
                print(f'[회전] 실패: {e}')

    def _update_label(self):
        global _loaded_json
        json_status = f"JSON: {_loaded_json['container']['id']}" if _loaded_json else "JSON: not loaded"
        self.count_label.text = f"Photos: {len(self.photos)}  |  {json_status}"

    def pick_json(self, *args):
        """Android Intent로 파일 관리자 열기"""
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.READ_EXTERNAL_STORAGE,
            ])
        except Exception:
            pass

        try:
            from jnius import autoclass, cast
            from android import mActivity

            Intent = autoclass('android.content.Intent')
            String = autoclass('java.lang.String')

            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.setType(String('*/*'))
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.putExtra(Intent.EXTRA_LOCAL_ONLY, True)

            chooser = Intent.createChooser(intent, String('Select JSON file'))

            # Pydroid3 방식: mActivity로 직접 실행
            mActivity.startActivityForResult(chooser, 9001)

            # 결과 콜백 바인딩
            from android import activity
            activity.bind(on_activity_result=self._on_activity_result)

        except Exception as e:
            print(f'[Intent] 실패: {e}')
            self._show_path_input()

    def _on_activity_result(self, requestCode, resultCode, intent):
        """파일 관리자 선택 결과 수신"""
        try:
            from android import activity
            activity.unbind(on_activity_result=self._on_activity_result)

            if requestCode != 9001 or resultCode != -1 or intent is None:
                return

            uri = intent.getData()
            if uri is None:
                return

            # InputStream으로 직접 읽기 (가장 안정적)
            self._load_from_uri(uri)

        except Exception as e:
            print(f'[ActivityResult] 오류: {e}')
            Clock.schedule_once(lambda dt: self._show_path_input(), 0)

    def _load_from_uri(self, uri):
        """URI InputStream으로 JSON 직접 읽기"""
        try:
            from jnius import autoclass
            from android import mActivity

            stream = mActivity.getContentResolver().openInputStream(uri)
            Scanner = autoclass('java.util.Scanner')
            sc = Scanner(stream).useDelimiter('\\A')
            content = sc.next() if sc.hasNext() else ''
            stream.close()

            import json as _json
            global _loaded_json
            _loaded_json = _json.loads(content)
            Clock.schedule_once(lambda dt: self._update_label(), 0)
            print('[JSON] 로드 성공 (URI stream)')
        except Exception as e:
            print(f'[URI Stream] {e}')
            Clock.schedule_once(lambda dt: self._show_path_input(), 0)

    def _show_path_input(self):
        """파일 선택 팝업 - 자주 쓰는 경로 버튼 + 직접 입력"""
        import os
        from kivy.uix.popup import Popup
        from kivy.uix.textinput import TextInput
        from kivy.uix.scrollview import ScrollView

        content = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))

        # 자주 쓰는 경로에서 JSON 파일 자동 탐색
        common_dirs = [
            '/storage/emulated/0/Download',
            '/storage/emulated/0/Documents',
            '/storage/emulated/0/',
            '/sdcard/Download',
            '/sdcard/',
        ]

        found_files = []
        for d in common_dirs:
            try:
                if os.path.isdir(d):
                    for fname in sorted(os.listdir(d)):
                        if fname.endswith('.json'):
                            found_files.append(os.path.join(d, fname))
            except Exception:
                pass

        # 찾은 파일 버튼 목록
        if found_files:
            lbl = KLabel(
                text=f'Found {len(found_files)} JSON file(s) — tap to load:',
                font_size=dp(12), color=(0.7, 1, 0.7, 1),
                size_hint=(1, None), height=dp(28), halign='left',
            )
            content.add_widget(lbl)

            scroll = ScrollView(size_hint=(1, None), height=dp(min(len(found_files), 5) * dp(42)))
            file_list = BoxLayout(orientation='vertical', spacing=dp(4),
                                  size_hint_y=None)
            file_list.bind(minimum_height=file_list.setter('height'))

            for fpath in found_files:
                fname = os.path.basename(fpath)
                fdir  = os.path.dirname(fpath)
                btn = KButton(
                    text=f'{fname}\n{fdir}',
                    font_size=dp(11),
                    background_normal='',
                    background_color=(0.15, 0.4, 0.6, 1),
                    halign='left',
                    size_hint=(1, None), height=dp(40),
                )
                btn._fpath = fpath
                btn.bind(on_release=self._on_file_btn)
                file_list.add_widget(btn)

            scroll.add_widget(file_list)
            content.add_widget(scroll)
        else:
            lbl = KLabel(
                text='No JSON files found in Download/Documents.',
                font_size=dp(12), color=(1, 0.6, 0.4, 1),
                size_hint=(1, None), height=dp(28),
            )
            content.add_widget(lbl)

        # 구분선
        content.add_widget(KLabel(
            text='── or enter path manually ──',
            font_size=dp(11), color=(0.5, 0.5, 0.6, 1),
            size_hint=(1, None), height=dp(24), halign='center',
        ))

        # 직접 입력
        self._path_input = TextInput(
            hint_text='/storage/emulated/0/Download/packing_result.json',
            multiline=False, font_size=dp(11),
            size_hint=(1, None), height=dp(38),
        )
        content.add_widget(self._path_input)

        btn_row = BoxLayout(orientation='horizontal', spacing=dp(8),
                            size_hint=(1, None), height=dp(40))
        btn_cancel = KButton(
            text='Cancel', font_size=dp(13),
            background_normal='', background_color=(0.3, 0.3, 0.35, 1),
            size_hint=(0.4, 1),
        )
        btn_ok = KButton(
            text='Load', font_size=dp(13),
            background_normal='', background_color=(0.2, 0.7, 0.3, 1),
            size_hint=(0.6, 1),
        )
        btn_row.add_widget(btn_cancel)
        btn_row.add_widget(btn_ok)
        content.add_widget(btn_row)

        self._popup = Popup(
            title='Select JSON File',
            content=content,
            size_hint=(0.95, 0.75),
            background_color=(0.1, 0.1, 0.15, 1),
        )
        btn_cancel.bind(on_release=self._popup.dismiss)
        btn_ok.bind(on_release=self._on_path_ok)
        self._popup.open()

    def _on_file_btn(self, btn):
        self._popup.dismiss()
        self._load_json_file(btn._fpath)

    def _on_path_ok(self, *args):
        path = self._path_input.text.strip()
        self._popup.dismiss()
        if path:
            self._load_json_file(path)

    def _load_json_file(self, path):
        global _loaded_json
        try:
            import json as _json
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            _loaded_json = data
            self._update_label()
            print(f'[JSON] 로드 성공: {path}')
        except Exception as e:
            print(f'[JSON] 로드 실패: {e}')
            self.count_label.text = f'JSON load failed: {e}'

    def go_next(self, *args):
        app = App.get_running_app()
        app.photos = self.photos
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'organize'

    def go_back(self, *args):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'select'


# ─────────────────────────────────────────────
# 3화면: 창고 정리
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# 사진 상세 화면 (체크박스)
# ─────────────────────────────────────────────
# 사진별 체크박스 상태 저장
_photo_meta = {}  # {filepath: {'frequent': bool, 'fragile': bool, 'stackable': bool}}

class PhotoDetailScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._filepath = None
        self._idx = None

    def load(self, filepath, idx):
        self._filepath = filepath
        self._idx = idx
        self.clear_widgets()
        self._build_ui()

    def _build_ui(self):
        from kivy.uix.image import Image as KvImage
        from kivy.uix.checkbox import CheckBox

        root = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(12))

        # 상단 바
        top = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(44), spacing=dp(8))
        btn_back = KButton(
            text='< Back', font_size=dp(13),
            background_normal='', background_color=(0.2, 0.2, 0.28, 1),
            color=(0.8, 0.8, 0.9, 1), size_hint=(None, 1), width=dp(80),
        )
        btn_back.bind(on_release=self._go_back)
        title = KLabel(
            text=f'Photo {self._idx+1}',
            font_size=dp(16), bold=True, color=(1,1,1,1),
            size_hint=(1,1), halign='center',
        )
        top.add_widget(btn_back)
        top.add_widget(title)
        root.add_widget(top)

        # 사진
        img = KvImage(
            source=self._filepath,
            size_hint=(1, 0.55),
            fit_mode='contain',
        )
        root.add_widget(img)

        # 체크박스 영역
        check_area = BoxLayout(
            orientation='vertical',
            size_hint=(1, None), height=dp(160),
            spacing=dp(8), padding=dp(12),
        )
        with check_area.canvas.before:
            Color(0.12, 0.14, 0.2, 1)
            _cbg = RoundedRectangle(pos=check_area.pos, size=check_area.size, radius=[dp(12)])
            check_area.bind(pos=lambda w,v: setattr(_cbg,'pos',v),
                            size=lambda w,v: setattr(_cbg,'size',v))

        meta = _photo_meta.get(self._filepath, {
            'frequent': False, 'fragile': False, 'stackable': False
        })

        checks = [
            ('frequent',  '자주 꺼내는 물건인가?'),
            ('fragile',   '취급 주의 물건인가?'),
            ('stackable', '위에 물건을 올릴 수 있나?'),
        ]

        self._checkboxes = {}
        for key, label_text in checks:
            row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(44))
            cb = CheckBox(
                active=meta.get(key, False),
                size_hint=(None, 1), width=dp(44),
                color=(0.3, 0.8, 1, 1),
            )
            cb._key = key
            cb.bind(active=self._on_check)
            self._checkboxes[key] = cb
            lbl = KLabel(
                text=label_text,
                font_size=dp(14), color=(1,1,1,1),
                size_hint=(1,1), halign='left', valign='middle',
            )
            lbl.bind(size=lambda w,v: setattr(w,'text_size',v))
            row.add_widget(cb)
            row.add_widget(lbl)
            check_area.add_widget(row)

        root.add_widget(check_area)
        root.add_widget(Label(size_hint=(1,1)))  # 여백
        self.add_widget(root)

    def _on_check(self, checkbox, value):
        if self._filepath not in _photo_meta:
            _photo_meta[self._filepath] = {'frequent': False, 'fragile': False, 'stackable': False}
        _photo_meta[self._filepath][checkbox._key] = value

    def _go_back(self, *args):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'camera'


class OrganizeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._built = False

    def on_enter(self):
        if not self._built:
            self._built = True
            self._build_ui()

        app = App.get_running_app()
        photos = getattr(app, 'photos', [])
        warehouse = getattr(app, 'selected_warehouse', '?')
        print(f'[창고정리] 창고 유형: {warehouse}, 사진 수: {len(photos)}장')

    def _build_ui(self):
        root = BoxLayout(orientation='vertical', padding=dp(25), spacing=dp(15))

        title = KLabel(
            text='Warehouse Organizer',
            font_size=dp(24),
            bold=True,
            color=(1, 1, 1, 1),
            halign='center',
            size_hint=(1, 0.15),
        )
        root.add_widget(title)

        info = KLabel(
            text='물건을 분석하고 최적의 배치를 제안합니다',
            font_size=dp(14),
            color=(0.6, 0.7, 0.9, 1),
            halign='center',
            size_hint=(1, 0.08),
        )
        root.add_widget(info)

        content_area = BoxLayout(
            orientation='vertical',
            size_hint=(1, 0.55),
            padding=dp(10),
        )
        with content_area.canvas.before:
            Color(0.12, 0.14, 0.2, 1)
            self._bg = RoundedRectangle(pos=content_area.pos, size=content_area.size, radius=[dp(12)])
        content_area.bind(pos=lambda w, v: setattr(self._bg, 'pos', v))
        content_area.bind(size=lambda w, v: setattr(self._bg, 'size', v))

        btn_b = KButton(
            text='3D\nView',
            font_size=dp(20),
            bold=True,
            background_normal='',
            background_color=(0.6, 0.3, 0.9, 1),
            size_hint=(0.5, 0.4),
            pos_hint={'center_x': 0.5},
        )
        btn_b.bind(on_release=lambda x: self._go_viewer())
        content_area.add_widget(Label(size_hint=(1, 0.3)))
        content_area.add_widget(btn_b)
        content_area.add_widget(Label(size_hint=(1, 0.3)))

        root.add_widget(content_area)

        btn_back = KButton(
            text='< Home',
            font_size=dp(14),
            background_normal='',
            background_color=(0.2, 0.2, 0.25, 1),
            color=(0.7, 0.7, 0.8, 1),
            size_hint=(1, 0.1),
        )
        btn_back.bind(on_release=self.go_home)
        root.add_widget(btn_back)

        self.add_widget(root)

    def _go_viewer(self):
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'viewer3d'

    def go_home(self, *args):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'select'


# ─────────────────────────────────────────────
# 앱 진입점
# ─────────────────────────────────────────────
class WarehouseApp(App):
    selected_warehouse = None
    photos = []

    def build(self):
        self.title = '창고 정리 앱'

        # Storage 권한 자동 요청
        self._request_permissions()

        sm = ScreenManager()
        sm.add_widget(LoadingScreen(name='loading'))
        sm.add_widget(SelectWarehouseScreen(name='select'))
        sm.add_widget(CameraScreen(name='camera'))
        sm.add_widget(OrganizeScreen(name='organize'))
        sm.add_widget(Viewer3DScreen(name='viewer3d'))
        sm.add_widget(PhotoDetailScreen(name='photo_detail'))

        return sm

    def _request_permissions(self):
        try:
            from android.permissions import (
                request_permissions, check_permission, Permission
            )
            perms = [
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.CAMERA,
            ]
            # 아직 허용 안 된 권한만 요청
            needed = [p for p in perms if not check_permission(p)]
            if needed:
                request_permissions(needed, self._on_permissions_result)
                print(f'[권한] 요청: {needed}')
            else:
                print('[권한] 이미 모두 허용됨')
        except Exception as e:
            print(f'[권한] 요청 실패 (비안드로이드 환경): {e}')

    def _on_permissions_result(self, permissions, grants):
        for perm, granted in zip(permissions, grants):
            name = perm.split('.')[-1]
            print(f'[권한] {name}: {"허용" if granted else "거부"}')


if __name__ == '__main__':
    WarehouseApp().run()
