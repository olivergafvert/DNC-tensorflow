import warnings
warnings.filterwarnings('ignore')

import tensorflow as tf
import numpy as np
import getopt
import sys
import os

from dnc.dnc import DNC
from feedforward_controller import FeedforwardController
from memory_visualization import visualize_op

def llprint(message):
    sys.stdout.write(message)
    sys.stdout.flush()

def generate_data(batch_size, length, size):

    input_data = np.zeros((batch_size, 2 * length + 1, size), dtype=np.float32)
    target_output = np.zeros((batch_size, 2 * length + 1, size), dtype=np.float32)

    sequence = np.random.binomial(1, 0.5, (batch_size, length, size - 1))

    input_data[:, :length, :size - 1] = sequence
    input_data[:, length, -1] = 1  # the end symbol
    target_output[:, length + 1:, :size - 1] = sequence

    return input_data, target_output


def binary_cross_entropy(predictions, targets):

    return tf.reduce_mean(
        -1 * targets * tf.log(predictions) - (1 - targets) * tf.log(1 - predictions)
    )


if __name__ == '__main__':

    dirname = os.path.dirname(__file__)
    ckpts_dir = os.path.join(dirname , 'checkpoints')
    tb_logs_dir = os.path.join(dirname, 'logs')

    batch_size = 1
    input_size = output_size = 6
    series_length = 4
    max_input_length = 4
    sequence_max_length = (2*max_input_length+1)*series_length
    words_count = 10 # number of rows in memory matrix
    word_size = 10
    read_heads = 1

    learning_rate = 1e-4
    momentum = 0.9

    from_checkpoint = None
    iterations = 20000
    start_step = 0

    checkpoint_step = 5000
    visualize_step = 500
    images_dir = os.path.join(
        dirname,
        'images_max_len_{}_cells_qtty_{}_cell_size_{}'.format(
            sequence_max_length, words_count, word_size))
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    options,_ = getopt.getopt(sys.argv[1:], '', ['checkpoint=', 'iterations=', 'start=', 'length='])

    for opt in options:
        if opt[0] == '--checkpoint':
            from_checkpoint = opt[1]
        elif opt[0] == '--iterations':
            iterations = int(opt[1])
        elif opt[0] == '--start':
            start_step = int(opt[1])
        elif opt[0] == '--length':
            series_length = int(opt[1])
            sequence_max_length = 11 * int(opt[1])

    graph = tf.Graph()

    with graph.as_default():
        with tf.Session(graph=graph) as session:

            llprint("Building Computational Graph ... ")

            optimizer = tf.train.RMSPropOptimizer(learning_rate, momentum=momentum)
            summerizer = tf.summary.FileWriter(tb_logs_dir, session.graph)

            ncomputer = DNC(
                FeedforwardController,
                input_size,
                output_size,
                sequence_max_length,
                words_count,
                word_size,
                read_heads,
                batch_size
            )

            output, packed_memory_view = ncomputer.get_outputs()
            squashed_output = tf.clip_by_value(tf.sigmoid(output), 1e-6, 1. - 1e-6)

            loss = binary_cross_entropy(squashed_output, ncomputer.target_output)

            summeries = []

            gradients = optimizer.compute_gradients(loss)
            for i, (grad, var) in enumerate(gradients):
                if grad is not None:
                    summeries.append(tf.summary.histogram(var.name + '/grad', grad))
                    gradients[i] = (tf.clip_by_value(grad, -10, 10), var)

            apply_gradients = optimizer.apply_gradients(gradients)

            summeries.append(tf.summary.scalar("Loss", loss))

            summerize_op = tf.summary.merge(summeries)
            no_summerize = tf.no_op()

            llprint("Done!\n")

            llprint("Initializing Variables ... ")
            session.run(tf.global_variables_initializer())
            llprint("Done!\n")

            if from_checkpoint is not None:
                llprint("Restoring Checkpoint %s ... " % (from_checkpoint))
                ncomputer.restore(session, ckpts_dir, from_checkpoint)
                llprint("Done!\n")


            last_100_losses = []

            start = 0 if start_step == 0 else start_step + 1
            end = start_step + iterations + 1

            for i in range(start, end):
                llprint("\rIteration %d/%d" % (i, end - 1))

                input_series = []
                output_series = []

                for k in range(series_length):
                    input_data, target_output = generate_data(batch_size, np.random.randint(1, max_input_length), input_size)
                    input_series.append(input_data)
                    output_series.append(target_output)

                one_big_input = np.concatenate(input_series, axis=1)
                one_big_output = np.concatenate(output_series, axis=1)

                summerize = (i % 100 == 0)
                take_checkpoint = (i != 0) and (i % iterations == 0 or i % checkpoint_step == 0)

                loss_value, _, summary, mem_view, out = session.run([
                    loss,
                    apply_gradients,
                    summerize_op if summerize else no_summerize,
                    packed_memory_view,
                    squashed_output
                ], feed_dict={
                    ncomputer.input_data: one_big_input,
                    ncomputer.target_output: one_big_output,
                    ncomputer.sequence_length: one_big_input.shape[1]
                })

                last_100_losses.append(loss_value)
                if summary:
                    summerizer.add_summary(summary, i)

                if i%visualize_step == 0:
                    visualize_op(one_big_input, out, mem_view, images_dir, i)


                if summerize:
                    llprint("\n\tAvg. Logistic Loss: %.4f\n" % (np.mean(last_100_losses)))
                    last_100_losses = []

                

                if take_checkpoint:
                    llprint("\nSaving Checkpoint ... "),
                    ncomputer.save(session, ckpts_dir, 'model-%dx%d-r%d-s%d' % (words_count, word_size, read_heads, i))
                    llprint("Done!\n")
