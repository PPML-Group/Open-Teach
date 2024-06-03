import hydra
import numpy as np
import pyzed.sl as sl
import blosc as bl
import zmq
import cv2
import base64
import numpy as np
import pickle
import cv2
import numpy as np

VIZ_PORT_OFFSET = 500
DEPTH_PORT_OFFSET = 1000
# Pub/Sub classes for storing data from Realsense Cameras
class ZMQCameraPublisher(object):
    def __init__(self, host, port):
        self._host, self._port = host, port
        self._init_publisher()

    def _init_publisher(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        print('tcp://{}:{}'.format(self._host, self._port))
        self.socket.bind('tcp://{}:{}'.format(self._host, self._port))


    def pub_intrinsics(self, array):
        self.socket.send(b"intrinsics " + pickle.dumps(array, protocol = -1))

    def pub_rgb_image(self, rgb_image, timestamp):
        _, buffer = cv2.imencode('.jpg', rgb_image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        data = dict(
            timestamp = timestamp,
            rgb_image = base64.b64encode(buffer)
        )
        self.socket.send(b"rgb_image " + pickle.dumps(data, protocol = -1))

    def pub_depth_image(self, depth_image, timestamp):
        compressed_depth = bl.pack_array(depth_image, cname = 'zstd', clevel = 1, shuffle = bl.NOSHUFFLE)
        data = dict(
            timestamp = timestamp,
            depth_image = compressed_depth
        )
        self.socket.send(b"depth_image " + pickle.dumps(data, protocol = -1))

    def stop(self):
        print('Closing the publisher socket in {}:{}.'.format(self._host, self._port))
        self.socket.close()
        self.context.term()
        
# Publisher for image visualizers
class ZMQCompressedImageTransmitter(object):
    def __init__(self, host, port):
        self._host, self._port = host, port
        # self._init_push_socket()
        self._init_publisher()

    def _init_publisher(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind('tcp://{}:{}'.format(self._host, self._port))

    def _init_push_socket(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUSH)
        self.socket.bind('tcp://{}:{}'.format(self._host, self._port))

    def send_image(self, rgb_image):
        _, buffer = cv2.imencode('.jpg', rgb_image, [int(cv2.IMWRITE_WEBP_QUALITY), 10])
        self.socket.send(np.array(buffer).tobytes())

    def stop(self):
        print('Closing the publisher in {}:{}.'.format(self._host, self._port))
        self.socket.close()
        self.context.term()

def rescale_image(image, rescale_factor):
    width, height = int(image.shape[1] / rescale_factor), int(image.shape[0] / rescale_factor)
    return cv2.resize(image, (width, height), interpolation = cv2.INTER_AREA)

def stack_images(image_array):
    return np.hstack(image_array)

def rotate_image(image, angle):
        if angle == 90:
            image = cv2.rotate(image, cv2.ROTATE_90)
        elif angle == 180:
            image = cv2.rotate(image, cv2.ROTATE_180)
        elif angle == 270:
            image = cv2.rotate(image, cv2.ROTATE_270)
        
        return image

class ZedMiniCamera():
    # def __init__(self, stream_configs, cam_serial_num, cam_id, cam_configs, stream_oculus = False):
    def __init__(self, host, transformation_port, stream_oculus = False):
        # Disabling scientific notations
        np.set_printoptions(suppress=True)
        # self.cam_id = cam_id
        # self.cam_configs = cam_configs
        # self._cam_serial_num = cam_serial_num
        self._host = host
        self._transformation_port = transformation_port
        self._stream_oculus = stream_oculus

        # Different publishers to avoid overload
        self.rgb_publisher = ZMQCameraPublisher(
            host = self._host,
            port = self._transformation_port
        )
        
        if self._stream_oculus:
            self.rgb_viz_publisher = ZMQCompressedImageTransmitter(
                host = self._host,
                port = self._transformation_port + VIZ_PORT_OFFSET
                # port = '10505'
            )

        self.depth_publisher = ZMQCameraPublisher(
            host = self._host,
            port = self._transformation_port + DEPTH_PORT_OFFSET
        )

        # Starting the realsense pipeline
        self._start_zed_mini()

    def _start_zed_mini(self):
        self.zed = sl.Camera()

        # Create a InitParameters object and set configuration parameters
        init_params = sl.InitParameters()
        init_params.depth_mode = sl.DEPTH_MODE.ULTRA  # Use ULTRA depth mode
        init_params.coordinate_units = sl.UNIT.MILLIMETER  # Use meter units (for depth measurements)

        init_params.camera_resolution = sl.RESOLUTION.AUTO # Use HD720 opr HD1200 video mode, depending on camera type.
        init_params.camera_fps = 30  # Set fps at 30

        # Open the camera
        status = self.zed.open(init_params)
        if status != sl.ERROR_CODE.SUCCESS: #Ensure the camera has opened succesfully
            print("Camera Open : "+repr(status)+". Exit program.")
            exit()

        self.image = sl.Mat()
        self.depth = sl.Mat()

        # Create and set RuntimeParameters after opening the camera
        self.runtime_parameters = sl.RuntimeParameters()

    def stream(self):
        # Starting the zed mini stream
        # print(f"Started the zed mini pipeline for camera: {self._cam_serial_num}!")
        print("Starting stream on {}:{}...\n".format(self._host, self._transformation_port))
        
        if self._stream_oculus:
            print('Starting oculus stream on port: {}\n'.format(self._transformation_port + VIZ_PORT_OFFSET))

        while True:
            #try:
                # Grab an image, a RuntimeParameters object must be given to grab()
                if self.zed.grab(self.runtime_parameters) == sl.ERROR_CODE.SUCCESS:
                    # A new image is available if grab() returns SUCCESS
                    self.zed.retrieve_image(self.image, sl.VIEW.LEFT)
                    # Retrieve depth map. Depth is aligned on the left image
                    self.zed.retrieve_measure(self.depth, sl.MEASURE.DEPTH)
                    # # Retrieve colored point cloud. Point cloud is aligned on the left image.
                    # self.zed.retrieve_measure(point_cloud, sl.MEASURE.XYZRGBA)
                    timestamp = self.zed.get_timestamp(sl.TIME_REFERENCE.CURRENT)  # Get the timestamp at the time the image was captured

                    # color_image = rotate_image(color_image, self.cam_configs.rotation_angle)
                    # depth_image = rotate_image(depth_image, self.cam_configs.rotation_angle)
                    color_image = self.image.get_data()
                    depth_image = self.depth.get_data()

                    # # 显示图像
                    # cv2.imshow('Image', color_image)
                    # # 等待用户按下任意键退出窗口
                    # cv2.waitKey(3)
                    
                    # Publishing the rgb images
                    self.rgb_publisher.pub_rgb_image(color_image, timestamp.get_milliseconds())
                    # TODO - move the oculus publisher to a separate process - this cycle works at 40 FPS
                    if self._stream_oculus:
                        self.rgb_viz_publisher.send_image(rescale_image(color_image, 2)) # 640 * 360

                    # Publishing the depth images
                    self.depth_publisher.pub_depth_image(depth_image, timestamp.get_milliseconds())
                    # self.depth_publisher.pub_intrinsics(self.intrinsics_matrix) # Publishing inrinsics along with the depth publisher

            # except KeyboardInterrupt:
            #     break
        
        # print('Shutting down zed mini pipeline for camera {}.'.format(self.cam_id))
        # Close the camera
        self.zed.close()
        self.self.rgb_publisher.stop()
        if self._stream_oculus:
            self.rgb_viz_publisher.stop()
        self.depth_publisher.stop()
        self.pipeline.stop()

@hydra.main(version_base = '1.2', config_path = 'configs', config_name = 'network')
def main(config):
    # host = '192.168.2.58'
    # transformation_port = '8089'
    print(f"Host Address: {config.host_address}")
    print(f"Transformed Position Left Keypoint Port: {config.transformed_position_keypoint_port}")
    host = config.host_address
    transformation_port = config.cam_port_offset
    # transformation_port = '10505'
    while_publisher = ZedMiniCamera(host, transformation_port, True)
    while_publisher.stream()

if __name__ == '__main__':
    main()