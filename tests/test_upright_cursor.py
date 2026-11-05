import math
import unittest
from adaptive_prefix_pose import AdaptivePrefixPose
from pose_math import multiply


def orientation(yaw=0., pitch=0., roll=0.):
    # Independently construct world-vertical yaw, elevation, and body-forward roll.
    q = multiply((0., 0., math.sin(yaw/2), math.cos(yaw/2)),
                 multiply((math.sin(pitch/2), 0., 0., math.cos(pitch/2)),
                          (0., math.sin(roll/2), 0., math.cos(roll/2))))
    if q[3] < 0:
        q = tuple(-v for v in q)
    return {'orientation3':q[:3], 'touch_active':False, 'touch_value':b'\x00\x00'}


def replay(path):
    pose = AdaptivePrefixPose()
    frames = []
    for i, sample in enumerate(path):
        pose.feed(sample, i*.01)
        delta = pose.tick(i*.01)
        frames.append(delta or (0, 0))
    return pose, frames


class UprightCursorTests(unittest.TestCase):
    def test_horizontal_movement_stays_horizontal_for_tilted_starts(self):
        totals = []
        for roll in (-math.pi/3, 0., math.pi/3):
            for pitch in (-.3, 0., .3):
                with self.subTest(roll=roll,pitch=pitch):
                    pose, frames = replay(orientation(.7+max(0,i-30)*.003,pitch,roll) for i in range(150))
                    self.assertTrue(pose.summary()['calibrated'])
                    self.assertTrue(all(y == 0 for x,y in frames))
                    self.assertTrue(all(x <= 0 for x,y in frames))
                    totals.append(sum(x for x,y in frames))
        self.assertLess(max(totals),-200)
        self.assertLessEqual(max(totals)-min(totals),1)

    def test_vertical_movement_stays_vertical_for_tilted_starts(self):
        totals = []
        for roll in (-math.pi/3, 0., math.pi/3):
            pose, frames = replay(orientation(.7,.2+max(0,i-30)*.003,roll) for i in range(150))
            self.assertTrue(all(x == 0 for x,y in frames))
            self.assertTrue(all(y <= 0 for x,y in frames))
            totals.append(sum(y for x,y in frames))
        self.assertLess(max(totals),-200)
        self.assertLessEqual(max(totals)-min(totals),1)

    def test_twisting_remote_without_changing_pointing_direction_does_not_move(self):
        pose, frames = replay(orientation(.5,.3,math.sin(max(0,i-30)*.02)) for i in range(400))
        self.assertTrue(pose.summary()['calibrated'])
        self.assertTrue(all(delta == (0,0) for delta in frames))

    def test_heading_wrap_and_quaternion_sign_change_do_not_reverse_or_jump(self):
        _, normal = replay(orientation(max(0,i-30)*.003,.2,.7) for i in range(150))
        pose, wrapped = replay(orientation(3.+max(0,i-30)*.003,.2,.7) for i in range(150))
        self.assertEqual(pose.stats['jumps'],0)
        self.assertTrue(all(y == 0 and x <= 0 for x,y in wrapped))
        self.assertLessEqual(abs(sum(x for x,y in wrapped)-sum(x for x,y in normal)),1)
        self.assertLessEqual(max(abs(x) for x,y in wrapped),10)

    def test_vertical_start_waits_for_defined_heading_without_emitting_offset(self):
        pose, frames = replay(orientation(.4,math.pi/2,.7) for _ in range(40))
        self.assertIsNone(pose.reference_inverse)
        self.assertTrue(all(delta == (0,0) for delta in frames))
        for i in range(40,80):
            pose.feed(orientation(.4,math.pi/2-.15,.7),i*.01)
            self.assertIn(pose.tick(i*.01),(None,(0,0)))
        self.assertIsNotNone(pose.reference_inverse)

    def test_tracking_rebases_after_pointing_through_vertical_pole(self):
        pose, _ = replay(orientation(.4,.3,.7) for _ in range(40))
        for i in range(40,90):
            pose.feed(orientation(.4,min(math.pi/2,.3+(i-39)*.03),.7),i*.01)
            pose.tick(i*.01)
        self.assertGreater(pose.stats['geometryRejected'],0)
        for i in range(90,130):
            pose.feed(orientation(1.2,math.pi/2-.15,.7),i*.01)
            self.assertIn(pose.tick(i*.01),(None,(0,0)))


if __name__ == '__main__':
    unittest.main()
