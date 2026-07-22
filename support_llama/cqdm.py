import comfy.utils
from tqdm import tqdm
import sys


class cqdm:
    def __init__(self, iterable=None, total=None, desc="Processing", disable=False, **kwargs):
        self.iterable = iterable
        self.total = total
        self.desc = desc

        if iterable is not None and total is None:
            try:
                self.total = len(iterable)
            except (TypeError, AttributeError):
                self.total = None

        self.pbar = comfy.utils.ProgressBar(self.total) if self.total is not None else None

        self.tqdm = tqdm(
            iterable=self.iterable,
            total=self.total,
            desc=self.desc,
            disable=disable,
            dynamic_ncols=True,
            file=sys.stdout,
            **kwargs
        )

    def __iter__(self):
        if self.tqdm is None:
            return
        for item in self.tqdm:
            if self.pbar:
                self.pbar.update(1)
            yield item

    def update(self, n=1):
        if self.tqdm:
            self.tqdm.update(n)
        if self.pbar:
            self.pbar.update(n)

    def set_description(self, desc):
        if self.tqdm:
            self.tqdm.set_description(desc)

    def set_postfix(self, *args, **kwargs):
        if self.tqdm:
            self.tqdm.set_postfix(*args, **kwargs)
