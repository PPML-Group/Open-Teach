import zmq
import pickle
import threading
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseArray, Pose
import hydra


VR_FREQ = 60
class FrequencyTimer(object):
    def __init__(self, frequency_rate):
        self.time_available = 1e9 / frequency_rate

    def start_loop(self):
        self.start_time = time.time_ns()

    def end_loop(self):
        wait_time = self.time_available + self.start_time
        
        while time.time_ns() < wait_time:
            continue

class ZMQKeypointSubscriber(threading.Thread):
    def __init__(self, host, port, topic):
        self._host, self._port, self._topic = host, port, topic
        self._init_subscriber()

        # Topic chars to remove
        self.strip_value = bytes("{} ".format(self._topic), 'utf-8')

    def _init_subscriber(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.CONFLATE, 1)
        self.socket.connect('tcp://{}:{}'.format(self._host, self._port))
        self.socket.setsockopt(zmq.SUBSCRIBE, bytes(self._topic, 'utf-8'))

    def recv_keypoints(self, flags=None):
        if flags is None:
            raw_data = self.socket.recv()
            raw_array = raw_data.lstrip(self.strip_value)
            return pickle.loads(raw_array)
        else: # For possible usage of no blocking zmq subscriber
            try:
                raw_data = self.socket.recv(flags)
                raw_array = raw_data.lstrip(self.strip_value)
                return pickle.loads(raw_array)
            except zmq.Again:
                # print('zmq again error')
                return None
    def stop(self):
        print('Closing the subscriber socket in {}:{}.'.format(self._host, self._port))
        self.socket.close()
        self.context.term()

class TransformHandPositionCoordsToRos(Node):
    def __init__(self, host, transformation_port):
        super().__init__('transform_hand_position_coords_to_ros')
        print('keypoint transform ros')

        # 接收到的手部处理后数据
        # 24组数据
        self.original_hand_coords_subscriber = ZMQKeypointSubscriber(host, transformation_port, 'transformed_hand_coords')
        # 旋转平移矩阵
        self.original_hand_matrix_subscriber = ZMQKeypointSubscriber(host, transformation_port, 'transformed_hand_frame')
        # Timer
        self.timer = FrequencyTimer(VR_FREQ)

        # ros 发布
        self.hand_coords_publisher_ = self.create_publisher(PoseArray, "transformed_hand_coords", 10)
        self.hand_coords_array = PoseArray()
        self.hand_coords_array.header.frame_id = "transformed_hand_coords"
        self.hand_coords_array.header.stamp = self.get_clock().now().to_msg()

        self.hand_matrix_publisher_ = self.create_publisher(PoseArray, "transformed_hand_frame", 10)
        self.hand_matrix_array = PoseArray()
        self.hand_matrix_array.header.frame_id = "transformed_hand_frame"
        self.hand_matrix_array.header.stamp = self.get_clock().now().to_msg()
    
    def stream(self):
        while True:
            try:
                self.timer.start_loop()
                hand_coords_data = self.original_hand_coords_subscriber.recv_keypoints()
                hand_matrix_data = self.original_hand_matrix_subscriber.recv_keypoints()
                
                print('transform ros', hand_matrix_data)
                self.hand_coords_array.header.stamp = self.get_clock().now().to_msg()
                # 遍历数据并将每行数据添加到 PoseArray 中
                for row in hand_coords_data:
                    pose = Pose()
                    pose.position.x, pose.position.y, pose.position.z = row
                    self.hand_coords_array.poses.append(pose)
                self.hand_coords_publisher_.publish(self.hand_coords_array)
                
                self.hand_matrix_array.header.stamp = self.get_clock().now().to_msg()
                for row in hand_matrix_data:
                    pose = Pose()
                    pose.position.x, pose.position.y, pose.position.z = row
                    self.hand_matrix_array.poses.append(pose)
                self.hand_matrix_publisher_.publish(self.hand_matrix_array)
                    
                self.timer.end_loop()
            except:
                break
        
        self.original_hand_coords_subscriber.stop()
        self.original_hand_matrix_subscriber.stop()

        print('Stopping the keypoint transform ros process.')

@hydra.main(version_base = '1.2', config_path = 'configs', config_name = 'network')
def main(config):
    rclpy.init()
    # host = '192.168.2.58'
    # transformation_port = '8089'
    print(f"Host Address: {config.host_address}")
    print(f"Transformed Position Left Keypoint Port: {config.transformed_position_keypoint_port}")
    host = config.host_address
    transformation_port = config.transformed_position_keypoint_port
    while_publisher = TransformHandPositionCoordsToRos(host, transformation_port)
    while_publisher.stream()
    rclpy.shutdown()

if __name__ == '__main__':
    main()