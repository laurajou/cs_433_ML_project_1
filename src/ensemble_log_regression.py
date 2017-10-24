import sys
import os
from src.utils import create_csv_submission
import numpy as np
import pickle
import csv
from src.utils import sigmoid, batch_iter, dataloader, standardize, \
    build_polynomial, split_data_k_fold
sys.path.append(os.getcwd())


class Config(object):
    """Contains hyperparameters for the classifiers"""

    def __init__(self, batch_size, num_epochs, learning_rate, lambda_, mode='cv'):
        self.batch_size = batch_size
        self.num_epochs = num_epochs
        self.learning_rate = learning_rate
        # regularization constant
        self.lambda_ = lambda_
        # mode can be cv or train
        self.mode = mode


class LogisticClassifier(object):
    def __init__(self, config, train_set=(None, None), test_set=(None, None), label='0'):
        self.config = config
        self.train_data, self.train_labels = train_set
        if self.train_data is not None:
            self.weights = np.zeros((np.shape(self.train_data)[1]))
        self.best_weights = None

        self.test_data, self.test_labels = test_set
        # to record convergence history
        self.train_losses = []
        self.train_loss = None
        self.test_losses = []
        self.test_loss = None

        self.accuracy = 0
        self.best_accuracy = 0
        self.train_accuracy = 0
        self.test_predictions = None
        self.train_predictions = None

        self.label = label

    def __call__(self, input):
        """Forward pass of the logistic classifier.
        args:
            input (np.array) : row matrix of samples
        """
        return sigmoid(np.dot(input, self.weights))

    def loss(self, output, target):
        """Computes L_2 regularized least squares.
        args:
            output (np.array) : result of the classifier
            target (np.array(int)) : labels of the batch samples

        returns:
            loss (float) : value of the loss

        """
        loss = 1 / np.shape(target)[0] * np.dot((target - output).T, (target - output)) \
               + self.config.lambda_ * np.dot(self.weights.T, self.weights)
        return loss

    def grad(self, output, target):
        """Computes gradient of loss wrt the weights.
        args:
            output (np.array) : output of the generator on a batch of inputs
            target (np.array(int)) : labels of the batch

        returns:
            (np.array) : gradient of loss
        """
        return np.dot(output.T, (
            (self(output) - target) * sample_weights * self(output) * (
        1 - self(output)))) + self.config.lambda_ * self.weights

    def sdg(self, param, output, target, learning_rate):
        """Optimization routing : Stochastic Gradient Descent
        args :
            param (np.array) : parameters to be updated
            output (np.array) : output of the classifier
        returns :
            param (np.array) : updated parameters
        """
        param -= learning_rate * self.grad(output, target)
        return param

    def train(self, show_every=10):
        """Trains the classifier.

        Trains the classifier on part of the dataset.
        """
        # reduce learning rate
        reduction_factor = 1
        num_batches = int(np.shape(self.train_data)[0] / self.config.batch_size)
        for epoch in range(self.config.num_epochs):
            # every fifty epoch half the learning rate
            if epoch % 50 == 0:
                reduction_factor *= 0.5

            for batch_label, batch_input in batch_iter(self.train_labels, self.train_data,
                    self.config.batch_size, num_batches=num_batches):
                # update weights
                self.weights = self.sdg(self.weights, batch_input, batch_label,
                                        self.config.learning_rate * reduction_factor)

            self.train_loss = self.loss(self(self.train_data), self.train_labels)
            # calculate train set performance
            if epoch % show_every == 0 or epoch == self.config.num_epochs - 1:
                self.train_predictions = self.predict(self(self.train_data))
                correct = np.sum(self.train_predictions == self.train_labels)
                self.train_accuracy = correct / np.shape(self.train_data)[0]

                print("Epoch : ", epoch)
                print("Train loss : ", self.train_loss)
                print("Train accuracy : ", self.train_accuracy)
                if self.config.mode == 'cv':
                    self.test()

    def test(self):
        """Tests classifier on test set"""
        output = self(self.test_data)
        self.test_loss = self.loss(output, self.test_labels)
        self.test_losses.append(self.test_loss)
        self.test_predictions = self.predict(output)
        correct = np.sum(self.test_predictions == self.test_labels)
        self.accuracy = correct / np.shape(self.test_data)[0]
        if self.accuracy > self.best_accuracy:
            self.best_accuracy = self.accuracy
            self.best_weights = self.weights
        print("Test loss :", self.test_loss)
        print('Test accuracy :', self.accuracy)

    def predict(self, output):
        """Predicts label from output of classifier"""
        return output > 0.5

    def save(self):
        """Save the weights of the model"""
        with open(r'config/weights' + self.label + '.p', "wb") as file:
            pickle.dump(self.weights, file)

    def load_weights(self):
        """Load the weights of the model from saved file"""
        self.weights = pickle.load(open('config/weights' + self.label + '.p', 'rb'))

    def export_predictions(self):
        """Custom prediction export into csv"""
        with open('prediction/submission.csv', 'w', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=',')
            for i in range(len(self.test_predictions)):
                writer.writerow([str(i) + ", " + self.test_predictions[i]])


class EnsembleClassifiers(object):
    """Ensemble of classifiers."""

    def __init__(self, config, x, y, num_classifiers, classifier, label='0'):
        self.train_data = x
        self.train_label = y
        self.config = config
        # init classifiers
        self.classifiers = []
        for i in range(num_classifiers):
            # if cross validation : apply k fold cross validation
            if config.mode == 'cv':
                train_set, test_set = split_data_k_fold(x, y, i % 10, k=10)
                self.classifiers.append(classifier(config, train_set, test_set))
            else:
                self.classifiers.append(
                    classifier(config, train_set=(self.train_data, self.train_label)))
        self.test_predictions = None
        self.label = label

    def __call__(self, data):
        """Calculates the mean of the outputs of the classifiers"""
        output = np.zeros(np.shape(data)[0])
        for classifier in self.classifiers:
            output += 1 / len(self.classifiers) * classifier(data)
        return output

    def predict(self, output):
        """Applies 0.5 treshold on output and tranforms 0 predictions to -1 and """
        y_pred = np.zeros(np.shape(output)[0])
        y_pred[np.where(output <= 0.5)] = -1
        y_pred[np.where(output > 0.5)] = 1
        return y_pred

    def train(self):
        """Trains the ensemble and if cv mode test it"""
        for classifier in self.classifiers:
            classifier.train()
        if self.config.mode == 'cv':
            self.test()

    def test(self):
        """test the ensemble on the cross validation set"""
        self.accuracy = 0
        for classifier in self.classifiers:
            self.accuracy += 1 / len(self.classifiers) * classifier.best_accuracy
        print('Test ensemble accuracy :', self.accuracy)

    def save(self):
        """Save weights of all classifiers of the ensemble"""
        weights = np.zeros((len(self.classifiers), np.shape(self.train_data)[1]))
        for i, classifier in enumerate(self.classifiers):
            weights[i] = classifier.weights
        with open(r'config/' + self.label + '.p', "wb") as file:
            pickle.dump(weights, file)

    def load_weights(self):
        """Load ensemble weights"""
        with open(r'config/' + self.label + '.p', "rb") as file:
            weights = pickle.load(file)

        for i, classifier in enumerate(self.classifiers):
            classifier.weights = weights[i]


def find_best_regularizer(model_class, lambdas):
    """Hyperparamenter search for regularization constant"""
    x, y = dataloader(mode='train', reduced=False)
    x = standardize(x)
    best_lambda = 0
    best_accuracy = 0
    for idx, lambda_ in enumerate(lambdas):
        print('Ensemble nr ' + str(idx) + 30 * '=')
        config = Config(batch_size=200, num_epochs=100, learning_rate=5 * 10 ** -4, lambda_=lambda_)
        ensemble = EnsembleClassifiers(config, build_polynomial(x), y, 10, LogisticClassifier,
                                       label='ensemble_' + str(idx))
        ensemble.train()
        print("ensemble accuracy " + str(ensemble.accuracy) + 30 * "=")
        if ensemble.accuracy > best_accuracy:
            best_accuracy = ensemble.accuracy
            best_lambda = lambda_
        print("best_lambda :", best_lambda)


if __name__ == '__main__':
    # find_best_regularizer(EnsembleClassifiers, np.logspace(-3, -2.5, 5))
    x, y = dataloader(mode='train', reduced=False)
    x_test = dataloader(mode='test', reduced=False)
    x = standardize(x)
    x_test = standardize(x_test)
    # # # train_dataset, test_dataset = split_data(x, y, ratio=0.9)
    # # # train_set = (build_polynomial(train_dataset[0]), train_dataset[1])
    # # # test_set = (build_polynomial(test_dataset[0]), test_dataset[1])
    # # # # x = dataloader(mode='test', reduced=False)
    # # # # x = standardize(x)
    # # # # x = build_polynomial(x)
    config = Config(batch_size=200, num_epochs=200, learning_rate=5 * 10 ** -4,
                    lambda_=0.00316227766017, mode='train')
    ensemble = EnsembleClassifiers(config, build_polynomial(x), y, 1, LogisticClassifier,
                                   label='ensemble_1_log')
    ensemble.train()
    ensemble.save()
    # ensemble.load_weights()
    predictions_test = ensemble.predict(ensemble(build_polynomial(x_test)))
    create_csv_submission(np.arange(350000, 350000 + x_test.shape[0]), predictions_test,
                          'dataset/submission_04.csv')

    predictions = ensemble.predict(ensemble(build_polynomial(x)))
    y[np.where(y == 0)] = -1
    accuracy = np.sum(predictions == y) / np.shape(x)[0]
    print("final accuracy : ", accuracy)
    # # print(predictions)
    # create_csv_submission(np.arange(350000, 350000 + x_test.shape[0]), predictions,
    #                                                             'dataset/submission_01.csv')
    # # y_test[np.where(y_test) == 0] = -1
    #
    # accuracy = np.sum(ensemble.predict(ensemble(build_polynomial(x))) == y)/np.shape(x)[0]
    # print("accuracy loaded weighs", accuracy)



    # model = LogisticClassifier(config, train_set, test_set)
    # find_best_lambda(model)
    # pred = ensemble(config, test_set=test_set, number=4)
    # acc = accuracy(pred, test_set[1])
    # print('accuracy ', acc)
    # create_csv_submission(np.arange(350000, 350000 + x.shape[0]), pred, \
    #                                                             '../dataset/submission_00.csv')

    # log_classifier = LogisticClassifier(config, train_set, test_set, label='log_4')
    # log_classifier.train()
    # log_classifier.save()
    # log_classifier.load_weights()
    # log_classifier.test()
    # ensemble = EnsembleClassifiers(config, train_set, test_set, 5, LogisticClassifier, "ensemble_0")
    # ensemble.train()
    best_lambda = .0133352143216
