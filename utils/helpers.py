#this module contains helpers functions

import random
class helpers:

    #a static function that returns a hash between 0 and 50000
    @staticmethod
    def get_hash(aString:str):
        return hash(aString) % 50000