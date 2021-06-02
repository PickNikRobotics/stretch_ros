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

        # Convenient aliases
        self.finger_rad_to_robotis = self.gripper_conversion.finger_to_robotis
        self.robotis_to_finger_rad = self.gripper_conversion.robotis_to_finger

    def get_position(self):
        return self.robotis_to_finger_rad(self.trajectory_manager.status['pos_pct'])

    def get_desired_position(self, dt):
        return self.robotis_to_finger_rad(self.trajectory_manager.trajectory.evaluate_at(dt).position)

    def add_waypoint(self, t, x, v, a):
        x = self.finger_rad_to_robotis(x)
        if v:
            v = self.finger_rad_to_robotis(v)
        if a:
            a = self.finger_rad_to_robotis(a)
        self.trajectory_manager.trajectory.add_waypoint(t, x, v, a)


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
        return to_transform(self.trajectory_manager.status)

    def get_desired_position(self, dt):
        # TODO: Fill in actual interpolated position
        return to_transform({'x': 0.0, 'y': 0.0, 'theta': 0.0})

    def add_waypoints(self, waypoints, index):
        self.trajectory_manager.trajectory.clear_waypoints()
        for waypoint in waypoints:
            t = to_sec(waypoint.time_from_start)
            x = waypoint.transforms[index]
            v = waypoint.velocities[index] if index < len(waypoint.velocities) else None
            a = waypoint.accelerations[index] if index < len(waypoint.accelerations) else None
            self.add_waypoint(t, x, v, a)
        self.trajectory_manager.trajectory.complete_trajectory()

    def add_waypoint(self, t, x, v, a):
        x = transform_to_triple(x)
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
