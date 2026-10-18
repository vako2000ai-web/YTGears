"""Panda3D application: procedural metal mechanism, porcelain and rigid-body fragments.

This is an interactive 3D prototype, not a finished Blender-authored cinematic.
"""
from __future__ import annotations

from pathlib import Path
import math
import random
import time

from panda3d.core import (AmbientLight, ClockObject, DirectionalLight, Filename, Fog, NodePath,
                         PNMImage, Point3, PointLight, Spotlight, TextNode, Texture, Vec3,
                         WindowProperties, load_prc_file_data)
from panda3d.bullet import BulletBoxShape, BulletConvexHullShape, BulletPlaneShape, BulletRigidBodyNode, BulletWorld
from direct.gui.DirectGui import DirectButton, DirectEntry, DirectFrame, DirectLabel, DirectWaitBar
from direct.showbase.ShowBase import ShowBase
import simplepbr
from simplepbr.envmap import EnvMap

from .core import Donation, MechanismRound, RoundParameters, RoundPhase, SpeedPolicy, physical_transmission
from .geometry import box, cylinder, gear, material, porcelain_texture, shard_mesh, vase_mesh

ROOT = Path(__file__).resolve().parents[1]


class GearPorcelainApp(ShowBase):
    def __init__(self, args):
        self.args = args
        self._offscreen = args.offscreen
        load_prc_file_data("ytgears", "\n".join((
            "window-title YTGears | Gear & Porcelain", "win-size 1600 900", "sync-video true",
            "framebuffer-multisample true", "multisamples 4", "textures-power-2 none",
            "gl-version 3 3", "notify-level warning", "background-color 0.015 0.022 0.032",
            "audio-library-name null" if args.offscreen else "audio-library-name p3openal_audio")))
        super().__init__(windowType="offscreen" if args.offscreen else None)
        self.disable_mouse()
        self.set_background_color(.012, .018, .028)
        self.camLens.set_fov(46)
        self.camLens.set_near_far(.1, 150)
        self.pipeline = simplepbr.init(msaa_samples=4, enable_shadows=True, max_lights=6,
                                      use_330=True, exposure=.8, env_map=self._environment())
        self._camera_angle = 0
        self._camera_distance = 19.5
        self._drag = None
        self._camera_position()
        self.accept("escape", self.userExit)
        self.accept("mouse1", self._begin_drag)
        self.accept("mouse1-up", self._end_drag)
        self.accept("wheel_up", self._zoom, [-1])
        self.accept("wheel_down", self._zoom, [1])
        self.accept("f11", self._fullscreen)
        self.accept("m", self._toggle_music)
        self.accept("space", self._toggle_pause)
        self.accept("f2", self._toggle_interface)
        self.accept("f12", self._screenshot)
        self.metal = material("brushed-steel", (.47, .55, .62), .92, .27)
        self.brass = material("satin-brass", (.65, .36, .105), .84, .25)
        self.dark = material("blackened-cast-iron", (.033, .046, .060), .65, .34)
        self.porcelain = material("glazed-porcelain", (.96, .97, .94), 0, .14)
        self.floor_material = material("basalt", (.006, .010, .017), .05, .52)
        self.texture = porcelain_texture()
        self._build_stage()
        self._lights()
        self._load_audio()
        self.round_number = 0
        self.paused = False
        self.music_enabled = True
        self.world = BulletWorld()
        self.world.set_gravity(Vec3(0, 0, -9.81))
        self._ground_collision()
        self.shards = []
        self.mechanism = self.render.attach_new_node("mechanism")
        self.vase = self.render.attach_new_node("vase-root")
        self._gui()
        self._start_round(demo=args.demo)
        self._last_time = time.perf_counter()
        self._capture_frames = 0
        self.taskMgr.add(self._update, "mechanism-update")

    def _environment(self):
        cube = Texture("studio-environment")
        cube.setup_cube_map(64, Texture.T_unsigned_byte, Texture.F_rgb)
        for face in range(6):
            image = PNMImage(64, 64, 3)
            for y in range(64):
                for x in range(64):
                    softbox = math.exp(-((x - 27) / 11)**8 - ((y - 19) / 22)**8) if face in (0, 2, 4) else 0
                    base = .14 if face == 4 else .035
                    image.set_xel(x, y, base + softbox * .85, base * 1.12 + softbox * .82, base * 1.4 + softbox * .75)
            cube.load(image, face, 0)
        return EnvMap(cube, prefiltered_size=32, prefiltered_samples=16, blocking_prepare=True)

    def _attach(self, mesh, parent, pos, mat):
        mesh.reparent_to(parent); mesh.set_pos(*pos); mesh.set_material(mat, 1)
        return mesh

    def _build_stage(self):
        self._attach(box("studio-floor", (200, 200, .2)), self.render, (0, 0, -.15), self.floor_material)
        # Raised porcelain display pedestal, physically represented in Bullet too.
        self.vase_pos = Vec3(3.9, 0, .65)
        self._attach(cylinder("pedestal", 1.22, .52, segments=96), self.render, (3.9, 0, .26), self.dark)
        self._attach(cylinder("pedestal-brass-edge", 1.235, .035, segments=96), self.render, (3.9, 0, .54), self.brass)
        self._attach(cylinder("pedestal-marble-top", 1.20, .08, segments=96), self.render, (3.9, 0, .60), self.floor_material)
        self._attach(box("gear-bed", (7.7, 1.65, .28)), self.render, (-2.85, .18, .24), self.dark)
        self._attach(box("bed-brass-line", (7.7, .025, .035)), self.render, (-2.85, -.66, .35), self.brass)
        for x in (-6.25, .5):
            for y in (-.35, .75):
                self._attach(cylinder("rubber-foot", .16, .16, segments=24), self.render, (x, y, .05), self.dark)
        fog = Fog("studio-depth"); fog.set_color(.012, .018, .028); fog.set_exp_density(.012)
        self.render.set_fog(fog)

    def _lights(self):
        ambient = AmbientLight("ambient"); ambient.set_color((.025, .035, .055, 1))
        self.render.set_light(self.render.attach_new_node(ambient))
        sun = DirectionalLight("large-softbox"); sun.set_color((1.7, 1.5, 1.3, 1))
        sun.set_shadow_caster(True, 2048, 2048)
        sun.get_lens().set_film_size(18, 13); sun.get_lens().set_near_far(.5, 45)
        node = self.render.attach_new_node(sun); node.set_pos(-3, -6, 12); node.look_at(0, 0, 0)
        self.render.set_light(node)
        fill = DirectionalLight("cool-rim"); fill.set_color((.5, .8, 1.4, 1))
        node = self.render.attach_new_node(fill); node.set_hpr(140, -35, 0); self.render.set_light(node)
        for name, pos, color in (("porcelain-key", (5, -3, 6), (3.5, 3.8, 4.2, 1)),
                                  ("warm-mechanism", (-4, 1, 4), (2.5, 1.6, .8, 1))):
            light = PointLight(name); light.set_color(color); light.set_attenuation((1, .02, .06))
            node = self.render.attach_new_node(light); node.set_pos(*pos); self.render.set_light(node)

    def _ground_collision(self):
        ground = BulletRigidBodyNode("ground")
        ground.add_shape(BulletPlaneShape(Vec3(0, 0, 1), -.05))
        self.render.attach_new_node(ground); self.world.attach_rigid_body(ground)
        # Convex cylinder support, matching the rendered top.
        from panda3d.bullet import BulletCylinderShape, ZUp
        pedestal = BulletRigidBodyNode("pedestal-collision")
        pedestal.add_shape(BulletCylinderShape(1.20, .64, ZUp))
        node = self.render.attach_new_node(pedestal); node.set_pos(3.9, 0, .32)
        self.world.attach_rigid_body(pedestal)

    def _load_audio(self):
        self.sounds = {}
        if self._offscreen: return
        from .audio import create_audio
        for name, path in create_audio(ROOT / ".cache" / "audio").items():
            self.sounds[name] = self.loader.load_sfx(Filename.from_os_specific(str(path)).get_fullpath())
        self.sounds["mechanism"].set_loop(True); self.sounds["mechanism"].set_volume(.11)
        self.sounds["music"].set_loop(True); self.sounds["music"].set_volume(.14)
        self.sounds["music"].play()

    def _gui(self):
        font_path = Path("C:/Windows/Fonts/segoeui.ttf")
        self.font = self.loader.load_font(Filename.from_os_specific(str(font_path)).get_fullpath()) if font_path.exists() else None
        if self.font: TextNode.set_default_font(self.font)
        self.ui = self.aspect2d.attach_new_node("interface")
        gold = (.78, .59, .31, 1)
        self.header = DirectLabel(parent=self.ui, text="GEAR & PORCELAIN", scale=.067,
                                  text_fg=gold, frameColor=(0, 0, 0, 0), text_align=TextNode.A_left, pos=(-1.67, 0, .84))
        DirectLabel(parent=self.ui, text="МЕТАЛЛ  /  ВРЕМЯ  /  ХРУПКИЙ ФАРФОР", scale=.024,
                    text_fg=(.50, .58, .63, 1), frameColor=(0, 0, 0, 0), text_align=TextNode.A_left, pos=(-1.66, 0, .775))
        self.mode_label = DirectLabel(parent=self.ui, text="", scale=.025, text_align=TextNode.A_right,
                                      text_fg=gold, frameColor=(0, 0, 0, 0), pos=(1.66, 0, .86))
        self.clock_label = DirectLabel(parent=self.ui, text="00:00", scale=.085, text_align=TextNode.A_right,
                                       text_fg=(.9, .93, .94, 1), frameColor=(0, 0, 0, 0), pos=(1.66, 0, .74))
        self.status_label = DirectLabel(parent=self.ui, text="", scale=.031, text_align=TextNode.A_right,
                                        text_fg=(.64, .71, .76, 1), frameColor=(0, 0, 0, 0), pos=(1.66, 0, .67))
        self.transmission_label = DirectLabel(parent=self.ui, text="", scale=.023, text_align=TextNode.A_left,
                                              text_fg=(.56, .64, .70, 1), frameColor=(0, 0, 0, 0), pos=(-1.66, 0, -.57))
        self.progress_bar = DirectWaitBar(parent=self.ui, range=100, value=0, frameSize=(-1.66, 1.66, -.007, .007),
                                          frameColor=(.09, .13, .16, 1), barColor=gold, pos=(0, 0, -.64), relief=None)
        self.bottom = DirectFrame(parent=self.ui, frameColor=(.015, .027, .040, .97), frameSize=(-1.77, 1.77, -.35, 0), pos=(0, 0, -.69))
        DirectLabel(parent=self.bottom, text="ВАЛЫ N", scale=.021, text_fg=(.55, .63, .7, 1), frameColor=(0, 0, 0, 0), pos=(-1.53, 0, -.055))
        DirectLabel(parent=self.bottom, text="ВРЕМЯ T, СЕК", scale=.021, text_fg=(.55, .63, .7, 1), frameColor=(0, 0, 0, 0), pos=(-1.24, 0, -.055))
        entry_style = dict(parent=self.bottom, scale=.038, width=4.5, numLines=1, frameColor=(.065, .09, .115, 1), text_fg=(.9, .93, .95, 1), entryFont=self.font)
        self.gears_entry = DirectEntry(**entry_style, initialText=str(5 if self.args.demo else self.args.gears), pos=(-1.61, 0, -.115))
        self.time_entry = DirectEntry(**entry_style, initialText=str(180 if self.args.demo else self.args.seconds), pos=(-1.33, 0, -.115))
        def button(text, x, command, width=.32):
            return DirectButton(parent=self.bottom, text=text, text_scale=.026, text_fg=(.86, .89, .91, 1),
                                frameColor=(.11, .15, .18, 1), frameSize=(-width / 2, width / 2, -.043, .043),
                                relief=None, pos=(x, 0, -.09), command=command, pressEffect=True)
        button("НОВЫЙ РАУНД", -.78, self._apply_settings, .43)
        self.pause_button = button("ПАУЗА", -.34, self._toggle_pause)
        button("+1 USD · ДЕМО", .12, self._donate, .48)
        button("ЗРИТЕЛИ +10", .64, self._more_viewers, .46)
        button("ДЕМО 30 СЕК", 1.18, lambda: self._start_round(True), .47)
        self.info_label = DirectLabel(parent=self.bottom, text="", scale=.024, text_align=TextNode.A_left,
                                      text_fg=(.60, .69, .75, 1), frameColor=(0, 0, 0, 0), pos=(-1.64, 0, -.19))
        DirectLabel(parent=self.bottom, text="F2 — чистый кадр   ·   F11 — полный экран   ·   M — музыка   ·   колесо — масштаб   ·   ЛКМ — поворот",
                    scale=.021, text_align=TextNode.A_left, text_fg=(.40, .49, .56, 1), frameColor=(0, 0, 0, 0), pos=(-1.64, 0, -.27))
        self.result_panel = DirectFrame(parent=self.ui, frameColor=(.018, .032, .047, .97), frameSize=(-.83, .83, -.43, .43), pos=(0, 0, .13))
        DirectLabel(parent=self.result_panel, text="ФАРФОР УСТУПИЛ ВРЕМЕНИ", scale=.046, text_fg=gold,
                    frameColor=(0, 0, 0, 0), pos=(0, 0, .29))
        self.result_text = DirectLabel(parent=self.result_panel, text="", scale=.035, text_fg=(.79, .85, .90, 1),
                                       frameColor=(0, 0, 0, 0), text_align=TextNode.A_left, pos=(-.65, 0, .16))
        self.result_panel.hide()
        self.error_label = DirectLabel(parent=self.ui, text="", scale=.032, text_fg=(1, .43, .3, 1),
                                       frameColor=(0, 0, 0, 0), text_wordwrap=80, pos=(0, 0, -.49))

    def _make_mechanism(self, transmission):
        self.mechanism.get_children().detach()
        pairs = transmission.stage_teeth
        units = sum((a + b) / 2 for a, b in pairs) + pairs[0][0] / 2 + pairs[-1][1] / 2 + 3
        module = 6.9 / units
        maximum_radius = max(b / 2 + 1 for _, b in pairs) * module
        axle_z = max(1.16, maximum_radius + .55)
        xs = [-6.0 + (pairs[0][0] / 2 + 1) * module]
        for a, b in pairs: xs.append(xs[-1] + (a + b) * module / 2)
        self.shafts = []
        for i, x in enumerate(xs):
            shaft = self.mechanism.attach_new_node(f"shaft-{i}"); shaft.set_pos(x, 0, axle_z); self.shafts.append(shaft)
            axle = self._attach(cylinder("steel-axle", .045, 1.25, segments=20), self.mechanism, (x, .10, axle_z), self.metal); axle.set_p(90)
            self._attach(box("bearing-support", (.15, .38, axle_z - .28)), self.mechanism, (x, .48, (axle_z + .28) / 2), self.dark)
            cap = self._attach(cylinder("brass-bearing", .105, .14, segments=32), self.mechanism, (x, -.56, axle_z), self.brass); cap.set_p(90)
        for i, (driver, driven) in enumerate(pairs):
            plane = -.29 if i % 2 == 0 else .13
            pinion = gear(driver, module, .13, self.brass); pinion.reparent_to(self.shafts[i]); pinion.set_y(plane)
            wheel = gear(driven, module, .13, self.metal); wheel.reparent_to(self.shafts[i + 1]); wheel.set_y(plane)
            wheel.set_r(180 / driven if driven % 2 == 0 else 0)
        # Visible cam and rod connect the final axle to the hammer support.
        cam = self._attach(cylinder("last-cam", .22, .10, segments=48), self.shafts[-1], (0, -.48, .08), self.brass); cam.set_p(90)
        end_x = xs[-1]
        self._attach(box("linkage-rod", (2.5 - end_x, .08, .08)), self.mechanism, ((2.5 + end_x) / 2, .43, axle_z), self.brass)
        for x in (2.25, 2.55):
            self._attach(box("hammer-bracket", (.12, .25, 2.9)), self.mechanism, (x, .55, 1.5), self.dark)
        axle = self._attach(cylinder("hammer-axle", .11, 1.2, segments=32), self.mechanism, (2.4, .2, 3.0), self.brass); axle.set_p(90)
        self.hammer = self.mechanism.attach_new_node("hammer-pivot"); self.hammer.set_pos(2.4, -.25, 3.0)
        self._attach(box("hammer-handle", (.10, .13, 1.95)), self.hammer, (0, 0, -.975), self.brass)
        head = self._attach(cylinder("hammer-head", .22, .65, segments=48), self.hammer, (0, 0, -1.95), self.metal); head.set_p(90)
        for y in (-.34, .34):
            ring = self._attach(cylinder("head-cap", .225, .045, segments=48), self.hammer, (0, y, -1.95), self.brass); ring.set_p(90)

    def _apply_settings(self):
        try:
            self._start_round(parameters=RoundParameters(int(self.gears_entry.get()), float(self.time_entry.get())))
        except ValueError as exc:
            self.error_label["text"] = str(exc)

    def _start_round(self, demo=False, parameters=None):
        parameters = parameters or (RoundParameters(5, 180) if demo else RoundParameters(self.args.gears, self.args.seconds))
        transmission = physical_transmission(parameters)  # Validate before changing the running scene.
        for node, body in self.shards:
            self.world.remove_rigid_body(body); node.remove_node()
        self.shards.clear()
        self.round_number += 1
        self.round = MechanismRound(f"local-{self.round_number}", policy=SpeedPolicy(), transmission=transmission)
        self.demo, self.viewers, self._viewer_refresh = demo, 51 if demo else 1, 0.0
        self.round.observe_viewers(self.viewers)
        self._make_mechanism(transmission)
        self.vase.get_children().detach()
        intact = vase_mesh(); intact.reparent_to(self.vase); intact.set_material(self.porcelain, 1); intact.set_texture(self.texture, 1)
        self.vase.set_pos(self.vase_pos); self.vase.show()
        self.paused, self.presentation_seconds = False, 0.0
        self.pause_button["text"] = "ПАУЗА"
        self.result_panel.hide(); self.error_label["text"] = ""
        self.gears_entry.enterText(str(parameters.gear_count)); self.time_entry.enterText(f"{parameters.target_seconds:g}")
        self.mode_label["text"] = "ИНТЕРАКТИВНЫЙ 3D-ПРОТОТИП  /  ЛОКАЛЬНЫЕ СОБЫТИЯ"
        pairs = " · ".join(f"{a}:{b}" for a, b in transmission.stage_teeth)
        self.transmission_label["text"] = f"{parameters.gear_count} валов · {2 * (parameters.gear_count - 1)} колёс · целые зубья {pairs} · точное T"
        if "mechanism" in self.sounds: self.sounds["mechanism"].play()
        if "music" in self.sounds: self.sounds["music"].set_volume(.14)
        self._last_time = time.perf_counter()

    def _donate(self):
        if self.round.phase == RoundPhase.RUNNING:
            self.round.receive_donation(Donation(self.round.round_id, "local-demo", f"button-{self.round.donation_count + 1}", 1))

    def _more_viewers(self):
        if self.round.phase == RoundPhase.RUNNING:
            self.viewers += 10; self.round.observe_viewers(self.viewers)

    def _toggle_pause(self):
        if self.round.phase != RoundPhase.RUNNING: return
        self.paused = not self.paused
        self.pause_button["text"] = "ПРОДОЛЖИТЬ" if self.paused else "ПАУЗА"
        self.pause_button["text_scale"] = .021 if self.paused else .026
        if "mechanism" in self.sounds:
            self.sounds["mechanism"].set_volume(0 if self.paused else .11)

    def _toggle_music(self):
        self.music_enabled = not self.music_enabled
        if "music" in self.sounds: self.sounds["music"].set_volume(.14 if self.music_enabled else 0)

    def _toggle_interface(self):
        self.ui.show() if self.ui.is_hidden() else self.ui.hide()

    def _fullscreen(self):
        props = WindowProperties(); props.set_fullscreen(not self.win.get_properties().get_fullscreen()); self.win.request_properties(props)

    def _camera_position(self, shake=0):
        angle = math.radians(self._camera_angle)
        self.camera.set_pos(math.sin(angle) * self._camera_distance + shake,
                            -math.cos(angle) * self._camera_distance, self._camera_distance * .43)
        self.camera.look_at(-.5, 0, 1.25)

    def _begin_drag(self):
        if self.mouseWatcherNode.has_mouse():
            pos = self.mouseWatcherNode.get_mouse()
            if -.56 < pos.y < .65: self._drag = pos.x

    def _end_drag(self): self._drag = None

    def _zoom(self, direction):
        self._camera_distance = max(10, min(28, self._camera_distance + direction))
        self._camera_position()

    def _screenshot(self):
        path = ROOT / "output" / f"ytgears-{time.strftime('%Y%m%d-%H%M%S')}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.win.save_screenshot(Filename.from_os_specific(str(path)))

    def _impact(self):
        self.round.begin_destruction()
        self.vase.hide()
        generator = random.Random(self.round_number)
        for i in range(160):
            mesh, center, points = shard_mesh(i)
            body = BulletRigidBodyNode(f"porcelain-{i}")
            shape = BulletConvexHullShape()
            for p in points: shape.add_point(Point3(p))
            shape.set_margin(.003)
            body.add_shape(shape); body.set_mass(.035); body.set_friction(.68); body.set_restitution(.16)
            body.set_ccd_motion_threshold(.02); body.set_ccd_swept_sphere_radius(.018)
            node = self.render.attach_new_node(body); node.set_pos(self.vase_pos + center)
            mesh.reparent_to(node); mesh.set_material(self.porcelain, 1); mesh.set_texture(self.texture, 1)
            self.world.attach_rigid_body(body)
            radial = Vec3(center.x, center.y, 0); radial.normalize()
            body.set_linear_velocity(radial * generator.uniform(1.3, 3.5) + Vec3(generator.uniform(.8, 2.1), generator.uniform(-.5, .5), generator.uniform(1.1, 3.6)))
            body.set_angular_velocity(Vec3(*(generator.uniform(-9, 9) for _ in range(3))))
            self.shards.append((node, body))
        if "mechanism" in self.sounds: self.sounds["mechanism"].stop()
        if "impact" in self.sounds: self.sounds["impact"].play()
        if "music" in self.sounds: self.sounds["music"].set_volume(.04 if self.music_enabled else 0)

    def _show_results(self):
        self.round.complete_destruction()
        r = self.round.result
        minutes, seconds = divmod(r.actual_seconds_to_impact, 60)
        self.result_text["text"] = (f"До контакта: {int(minutes):02d}:{seconds:05.2f}\n"
                                    f"Донатов: {r.donation_count}     Сумма: {r.donation_total_usd} USD\n"
                                    f"Пик имитируемого онлайна: {r.observed_peak_concurrent_viewers}\n"
                                    f"Уникальные зрители: недоступно\n"
                                    f"Уникальные ускорившие: недоступно\n"
                                    f"Максимальная скорость: ×{r.max_applied_multiplier:.2f}")
        self.result_panel.show()
        if "music" in self.sounds: self.sounds["music"].set_volume(.14 if self.music_enabled else 0)

    def _update(self, task):
        now = time.perf_counter()
        dt, self._last_time = now - self._last_time, now
        if self._offscreen: dt = 1 / 60
        if self._drag is not None and self.mouseWatcherNode.has_mouse():
            x = self.mouseWatcherNode.get_mouse().x
            self._camera_angle = max(-48, min(48, self._camera_angle + (x - self._drag) * 80)); self._drag = x
            self._camera_position()
        if self.round.phase == RoundPhase.RUNNING and not self.paused:
            if self._offscreen and self.args.capture_impact and self._capture_frames == 2:
                dt = self.round.transmission.parameters.target_seconds
            # Local simulator refreshes a known simulated count. No YouTube claim.
            self._viewer_refresh += dt
            if self._viewer_refresh >= 5:
                self.round.observe_viewers(self.viewers); self._viewer_refresh = 0
            before = self.round.elapsed_seconds
            if self.round.advance(dt):
                self._impact()
                self.presentation_seconds = max(0, dt - (self.round.elapsed_seconds - before)) if not self._offscreen else 0
            if "mechanism" in self.sounds:
                self.sounds["mechanism"].set_play_rate(min(2.5, self.round.applied_multiplier ** .22))
            for i, node in enumerate(self.shafts): node.set_r(self.round.transmission.angle_degrees(i, self.round.mechanism_seconds) % 360)
            p = self.round.progress
            angle = 15 + 70 * min(1, p / .985)
            if p > .985: angle = 85 - 105 * ((p - .985) / .015)**3
            self.hammer.set_r(angle)
        if self.round.phase == RoundPhase.DESTRUCTION:
            self.presentation_seconds += min(dt, .1)
            self.world.do_physics(min(dt, .1), 12, 1 / 120)
            shake = .07 * math.exp(-self.presentation_seconds * 7) * math.sin(self.presentation_seconds * 85)
            self._camera_position(shake)
            if self.presentation_seconds >= 6:
                self._show_results(); self._camera_position()
        elapsed = self.round.elapsed_seconds
        self.clock_label["text"] = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        state = "ПАУЗА" if self.paused else {RoundPhase.RUNNING: "Механизм взводится", RoundPhase.DESTRUCTION: "УДАР · ФАРФОР", RoundPhase.RESULTS: "ИТОГИ РАУНДА"}.get(self.round.phase, "Контакт")
        self.status_label["text"] = f"{state}   ·   ×{self.round.applied_multiplier:.2f}"
        self.progress_bar["value"] = self.round.progress * 100
        self.info_label["text"] = (f"Онлайн (имитация): {self.viewers}    ·    Донаты (имитация): {self.round.donation_count} / {self.round.donation_total_usd} USD"
                                   f"    ·    Предварительно: Mv=1+0.1(V−1), донат ×2 без накопления, предел ×64")
        self._capture_frames += 1
        if self.args.capture and self._capture_frames >= (90 if self.args.capture_impact else 8):
            path = Path(self.args.capture).resolve(); path.parent.mkdir(parents=True, exist_ok=True)
            self.graphicsEngine.render_frame(); self.win.save_screenshot(Filename.from_os_specific(str(path)))
            self.userExit()
        return task.cont
