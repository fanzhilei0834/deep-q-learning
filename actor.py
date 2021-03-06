import zmq
import numpy as np
from gym.wrappers import Monitor
from tensorboardX import SummaryWriter

from utilities.environment import get_env
from utilities.agent import Actor
from utilities.data import Data, arr2bytes
import tensorflow as tf
from tensorflow.keras import backend as K
import horovod.tensorflow.keras as hvd

hvd.init()

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
config.gpu_options.visible_device_list = str(hvd.local_rank())
K.set_session(tf.Session(config=config))

callbacks = [hvd.callbacks.BroadcastGlobalVariablesCallback(0)]

if __name__ == '__main__':
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind("tcp://*:6659")

    writer = SummaryWriter('logs')

    env = get_env('PongNoFrameskip-v4', 4)
    env = Monitor(env, 'video', video_callable=lambda ep: ep % 50 == 0, force=True)

    action_size = env.action_space.n
    state_size = env.observation_space.shape
    actor = Actor(state_size, action_size)

    num_steps = 1000000
    episode_rewards = [0.0]

    state = env.reset()
    for step in range(num_steps):

        weight = socket.recv()
        if len(weight):
            actor.load(weight, 'model.h5')

        actor.adjust_ep(step)
        action = actor.act(state)
        next_state, reward, done, info = env.step(action)

        data = Data(state=arr2bytes(state), next_state=arr2bytes(next_state), action=int(action),
                    reward=reward, done=done, epoch=step)
        socket.send(data.SerializeToString())

        state = next_state
        episode_rewards[-1] += reward

        if done:
            num_episodes = len(episode_rewards)
            mean_100ep_reward = round(np.mean(episode_rewards[-100:]), 2)

            print('episode: {}, step: {}/{}, mean reward: {}, epsilon: {:.3f}'.format(
                num_episodes, step+1, num_steps, mean_100ep_reward, actor.epsilon))
            writer.add_scalar('reward', mean_100ep_reward, num_episodes)
            writer.add_scalar('epsilon', actor.epsilon, num_episodes)
            writer.flush()

            state = env.reset()
            episode_rewards.append(0.0)
