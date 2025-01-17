# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/10_data-seq2seq-core.ipynb (unless otherwise specified).

__all__ = ['HF_Seq2SeqInput', 'default_text_gen_kwargs', 'HF_Seq2SeqBeforeBatchTransform',
           'HF_Seq2SeqAfterBatchTransform', 'HF_Seq2SeqBlock']

# Cell
from functools import reduce

import torch
from transformers import *
from fastai.text.all import *

from ...utils import *
from ..core import *

logging.set_verbosity_error()

# Cell
class HF_Seq2SeqInput(HF_BaseInput): pass

# Cell
def default_text_gen_kwargs(hf_config, hf_model, task=None):
    text_gen_kwargs = {}
    hf_config_dict = hf_config.to_dict()

    generate_func_args = list(inspect.signature(hf_model.generate).parameters.keys())
    for k in generate_func_args:
        if (k in hf_config_dict): text_gen_kwargs.update({k: hf_config_dict[k]})

    # not all configs even have a task_specific_params property
    if (task is not None):
        try:
            text_gen_kwargs = { **text_gen_kwargs, **hf_config.task_specific_params[task] }
        except: pass

    return text_gen_kwargs

# Cell
class HF_Seq2SeqBeforeBatchTransform(HF_BeforeBatchTransform):

    def __init__(self, hf_arch, hf_config, hf_tokenizer, hf_model,
                 ignore_token_id=CrossEntropyLossFlat().ignore_index,
                 max_length=None, max_target_length=None, padding=True, truncation=True,
                 tok_kwargs={}, text_gen_kwargs={}, **kwargs):

        super().__init__(hf_arch, hf_config, hf_tokenizer, hf_model,
                         max_length=max_length, padding=padding, truncation=truncation, is_split_into_words=False,
                         tok_kwargs=tok_kwargs.copy(), **kwargs)

        store_attr(self=self, names='text_gen_kwargs, max_target_length, ignore_token_id')

    def encodes(self, samples):
        samples = L(samples)

        # tokenize
        src_texts=samples.itemgot(0).items
        tgt_texts=samples.itemgot(1).items if (len(samples[0]) > 1) else None

        tok_d = self.hf_tokenizer(src_texts, max_length=self.max_length, padding=self.padding,
                                  truncation=self.truncation, return_tensors='pt', **self.tok_kwargs)

        if (tgt_texts):
            with self.hf_tokenizer.as_target_tokenizer():
                tok_d_targs = self.hf_tokenizer(tgt_texts, max_length=self.max_target_length, padding=self.padding,
                                      truncation=self.truncation, return_tensors='pt', **self.tok_kwargs)

                tok_d['labels'] = tok_d_targs['input_ids']

        # add in target ids for us to use if fastai is calculating the loss
        targ_ids = [[]] * len(samples)
        if ('labels' in tok_d):
            tok_d['labels'].masked_fill_(tok_d['labels'] == self.ignore_token_id, self.hf_tokenizer.pad_token_id)
            targ_ids = tok_d['labels'].clone()

        # update samples with tokenized inputs (e.g. input_ids, attention_mask, etc...)
        d_keys = tok_d.keys()
        updated_samples= [ (*[{k: tok_d[k][idx] for k in d_keys}], *tuplify(targ_ids[idx]), *sample[2:])
                          for idx, sample in enumerate(samples) ]

        return updated_samples

# Cell
class HF_Seq2SeqAfterBatchTransform(HF_AfterBatchTransform):
    def decodes(self, encoded_samples):
        input_ids = encoded_samples['input_ids'] if (isinstance(encoded_samples, dict)) else encoded_samples
        return self.input_return_type(input_ids, hf_tokenizer=self.hf_tokenizer)


class HF_Seq2SeqBlock(HF_TextBlock):

    def __init__(self, hf_arch=None, hf_config=None, hf_tokenizer=None, hf_model=None,
                 before_batch_tfm=None, after_batch_tfm=None,
                 max_length=None, max_target_length=None, padding=True, truncation=True,
                 input_return_type=HF_Seq2SeqInput, dl_type=SortedDL,
                 tok_kwargs={}, text_gen_kwargs={}, before_batch_kwargs={}, after_batch_kwargs={}, **kwargs):

        # we need to pass text_gen_kwargs into our HF_Seq2SeqBeforeBatchTransform (use default unless specified)
        if (len(text_gen_kwargs) == 0):
            if (hf_config is None): hf_config = before_batch_tfm.hf_config
            if (hf_model is None): hf_model = before_batch_tfm.hf_model
            self.text_gen_kwargs = default_text_gen_kwargs(hf_config, hf_model)
        else:
            self.text_gen_kwargs = text_gen_kwargs.copy()

        # construct our before_batch and after_batch tfms as usual
        if (before_batch_tfm is None):
            before_batch_tfm = HF_Seq2SeqBeforeBatchTransform(hf_arch, hf_config, hf_tokenizer, hf_model,
                                                              max_length=max_length,
                                                              max_target_length=max_target_length,
                                                              padding=padding,
                                                              truncation=truncation,
                                                              tok_kwargs=tok_kwargs.copy(),
                                                              text_gen_kwargs=text_gen_kwargs,
                                                              **before_batch_kwargs.copy())

        if (after_batch_tfm is None):
            hf_tokenizer = hf_tokenizer if (hf_tokenizer is not None) else before_batch_tfm.hf_tokenizer
            after_batch_tfm = HF_Seq2SeqAfterBatchTransform(hf_tokenizer, input_return_type,
                                                            **after_batch_kwargs.copy())

        return super().__init__(before_batch_tfm=before_batch_tfm, after_batch_tfm=after_batch_tfm,
                                max_length=max_length, padding=padding, truncation=truncation,
                                is_split_into_words=False,
                                input_return_type=input_return_type, dl_type=dl_type,
                                tok_kwargs=tok_kwargs,
                                before_batch_kwargs=before_batch_kwargs,
                                after_batch_kwargs=after_batch_kwargs,
                                **kwargs)

# Cell
@typedispatch
def show_batch(x:HF_Seq2SeqInput, y, samples, dataloaders, ctxs=None, max_n=6,
               input_trunc_at=None, target_trunc_at=None, **kwargs):
    # grab our tokenizer and ignore token to decode
    hf_before_batch_tfm = get_blurr_tfm(dataloaders.before_batch)
    hf_tokenizer = hf_before_batch_tfm.hf_tokenizer
    ignore_token_id = hf_before_batch_tfm.ignore_token_id

    res = L([ (hf_tokenizer.decode(s[0], skip_special_tokens=False)[:input_trunc_at],
               hf_tokenizer.decode(s[1][s[1] != ignore_token_id], skip_special_tokens=True)[:target_trunc_at])
             for s in samples ])

    display_df(pd.DataFrame(res, columns=['text', 'target'])[:max_n])
    return ctxs