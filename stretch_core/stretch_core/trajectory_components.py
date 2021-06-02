from hello_helpers.gripper_conversion import GripperConversion
from hello_helpers.hello_misc import to_sec, to_transform, transform_to_triple, twist_to_pair


class TrajectoryComponent:
    def __init__(self, name, trajectory_manager):
        self.name = name
        self.trajectory_manager = trajectory_manager

    def get_position(self):
        return self.trajectory_manager.status['pos']

    def get_velocity(self):
        return self.trajectory_manager.status['vel']

    def get_desired_position(self, dt):
        return self.trajectory_manager.trajectory.evaluate_at(dt).position

    def add_waypoints(self, waypoints, index):
        # Set Initial waypoint
        self.trajectory_manager.trajectory.clear_waypoints()
        for waypoint in waypoints:
            t = to_sec(waypoint.time_from_start)
            x = waypoint.positions[index]
            v = waypoint.velocities[index] if index < len(waypoint.velocities) else None
            a = waypoint.accelerations[index] if index < len(waypoint.accelerations) else None
            self.add_waypoint(t, x, v, a)

    def add_waypoint(self, t, x, v, a):
        self.trajectory_manager.trajectory.add_waypoint(t, x, v, a)


class HeadPanComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'joint_head_pan', robot.head.get_joint('head_pan'))


class HeadTiltComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'joint_head_tilt', robot.head.get_joint('head_tilt'))


class WristYawComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'joint_wrist_yaw', robot.end_of_arm.motors['wrist_yaw'])


class GripperComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'stretch_gripper', robot.end_of_arm.motors['stretch_gripper'])
        self.gripper_conversion = GripperConversion()

    def get_position(self):
        robotis = self.trajectory_manager.status['pos_pct']
        finger_rad = self.gripper_conversion.robotis_to_finger(robotis)
        return finger_rad

    def get_desired_position(self, dt):
        return self.trajectory_manager.trajectory.evaluate_at(dt).position

#        for pt in trajectory.points:
 #           finger_rad = pt.positions[gripper_index]
  #          pct = 500.0 * finger_rad / 0.3
   #         pt.positions[gripper_index] = gripper.pct_to_world_rad(pct)


class ArmComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'wrist_extension', robot.arm)


class LiftComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'joint_lift', robot.lift)


class BaseComponent(TrajectoryComponent):
    def __init__(self, robot):
        TrajectoryComponent.__init__(self, 'position', robot.base)

    def get_position(self):
        return to_transform(self.trajectory_manager.status['pos'])

    def add_waypoints(self, waypoints, index):
        TrajectoryComponent.add_waypoints(self, waypoints, index)
        self.trajectory_manager.trajectory.complete_trajectory()

    def add_waypoint(self, t, x, v, a):
        x = transform_to_triple(t)
        if v is not None:
            v = twist_to_pair(v)
        if a is not None:
            a = twist_to_pair(a)
        self.trajectory_manager.trajectory.add_waypoint(t, x, v, a)


def get_trajectory_components(robot):
    return {component.name: component for component in [HeadPanComponent(robot),
                                                        HeadTiltComponent(robot),
                                                        WristYawComponent(robot),
                                                        GripperComponent(robot),
                                                        ArmComponent(robot),
                                                        LiftComponent(robot),
                                                        BaseComponent(robot)]}
