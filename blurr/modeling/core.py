# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/02_modeling-core.ipynb (unless otherwise specified).

__all__ = ['hf_splitter', 'HF_BaseModelWrapper', 'HF_PreCalculatedLoss', 'HF_BaseModelCallback', 'blurr_module_summary',
           'blurrONNX']

# Cell
import inspect, torch
from transformers import *

from fastai.text.all import *
from fastai.callback.hook import _print_shapes

from ..utils import *
from ..data.core import *

logging.set_verbosity_error()

# Cell
def hf_splitter(m):
    """Splits the huggingface model based on various model architecture conventions"""
    model = m.hf_model if (hasattr(m, 'hf_model')) else m
    root_modules = list(model.named_children())
    top_module_name, top_module = root_modules[0]

    groups = L([ m for m_name, m in list(top_module.named_children()) ])
    groups += L([ m for m_name, m in root_modules[1:] ])

    return groups.map(params).filter(lambda el: len(el) > 0)

# Cell
class HF_BaseModelWrapper(Module):
    def __init__(self, hf_model, output_hidden_states=False, output_attentions=False, hf_model_kwargs={}):
        super().__init__()

        store_attr(self=self, names='output_hidden_states, output_attentions, hf_model_kwargs')
        self.hf_model = hf_model.cuda() if torch.cuda.is_available() else hf_model

        self.hf_model_fwd_args = list(inspect.signature(self.hf_model.forward).parameters.keys())

    def forward(self, x):
        for k in list(x):
            if k not in self.hf_model_fwd_args: del x[k]

        return self.hf_model(**x,
                             output_hidden_states=self.output_hidden_states,
                             output_attentions=self.output_attentions,
                             return_dict=True,
                             **self.hf_model_kwargs)

# Cell
class HF_PreCalculatedLoss():
    def __call__(self, inp, targ, **kwargs): return
    def decodes(self, x): return x.argmax(dim=-1)
    def activation(self, x): return F.softmax(x, dim=-1)

# Cell
class HF_BaseModelCallback(Callback):

    def before_batch(self): self.hf_loss = None

    def after_pred(self):
        model_outputs = self.pred
        self.learn.blurr_model_outputs = {}

        for k,v in model_outputs.items():
            # if the "labels" are included, we are training with target labels in which case the loss is returned
            if (k == 'loss' and isinstance(self.learn.loss_func, HF_PreCalculatedLoss)):
                self.hf_loss = to_float(v)
            # the logits represent the prediction
            elif (k == 'logits'):
                self.learn.pred = v
            # add any other things included in model_outputs as blurr_{model_output_key}
            else:
                self.learn.blurr_model_outputs[k] = v

    def after_loss(self):
        # if we already have the loss from the model, update the Learner's loss to be it
        if (self.hf_loss is not None): self.learn.loss = self.hf_loss

# Cell
def blurr_module_summary(learn, *xb):
    "Print a summary of `model` using `xb`"
    #Individual parameters wrapped in ParameterModule aren't called through the hooks in `layer_info`,
    #  thus are not counted inside the summary
    #TODO: find a way to have them counted in param number somehow
    infos = layer_info(learn, *xb)
    n,bs = 76,find_bs(xb)
    inp_sz = _print_shapes(apply(lambda x:x.shape,  xb[0]['input_ids']), bs)
    res = f"{type(learn.model).__name__} (Input shape: {inp_sz})\n"
    res += "=" * n + "\n"
    res += f"{'Layer (type)':<20} {'Output Shape':<20} {'Param #':<10} {'Trainable':<10}\n"
    res += "=" * n
    ps,trn_ps,j = 0,0,0
    infos = [o for o in infos if o is not None] #see comment in previous cell
    prev_sz = None
    for typ,np,trn,sz,chnged in infos:
        if sz is None: continue
        if j == 0:
            res += f'\n{"":<20} {_print_shapes(sz, bs)[:19]:<20}' # to avoid a double line at the top
        if not chnged and not prev_sz == sz and j > 0: res += "\n" + "_" * n + "\n" + f'{"":<20} {_print_shapes(sz, bs)[:19]:<20}'
        j = 1
        res += f"\n{typ:<20} {'':<20} {np:<10} {str(trn):<10}"
        if np is not '':
            ps += np
            if trn: trn_ps += np
        prev_sz = sz
    res += "\n" + "_" * n + "\n"
    res += f"\nTotal params: {ps:,}\n"
    res += f"Total trainable params: {trn_ps:,}\n"
    res += f"Total non-trainable params: {ps - trn_ps:,}\n\n"
    return PrettyString(res)

# Cell
@patch
def blurr_summary(self:Learner):
    "Print a summary of the model, optimizer and loss function."
    xb = self.dls.train.one_batch()[:self.dls.train.n_inp]
    res = blurr_module_summary(self, *xb)
    res += f"Optimizer used: {self.opt_func}\nLoss function: {self.loss_func}\n\n"
    if self.opt is not None:
        res += f"Model " + ("unfrozen\n\n" if self.opt.frozen_idx==0 else f"frozen up to parameter group #{self.opt.frozen_idx}\n\n")
    res += "Callbacks:\n" + '\n'.join(f"  - {cb}" for cb in sort_by_run(self.cbs))
    return PrettyString(res)

# Cell
@typedispatch
def show_results(x:HF_BaseInput, y, samples, outs, learner, ctxs=None, max_n=6, trunc_at=None, **kwargs):
    #grab tokenizer and trunc_at to pass into HF_BaseInput.show
    hf_before_batch_tfm = get_blurr_tfm(learner.dls.before_batch)
    kwargs['hf_tokenizer'] = hf_before_batch_tfm.hf_tokenizer
    kwargs['trunc_at'] = trunc_at

    if ctxs is None: ctxs = get_empty_df(min(len(samples), max_n))
    ctxs = show_batch[object](x, y, samples, max_n=max_n, ctxs=ctxs, **kwargs)

    n_preds_per_input = len(outs[0])
    if (n_preds_per_input == 1):
        for i,ctx in enumerate(ctxs): ctx['target'] = outs[i][0]
    else:
        for pred_idx in range(n_preds_per_input):
            for i,ctx in enumerate(ctxs):  ctx[f'target{pred_idx+1}'] = outs[i][pred_idx]

    display_df(pd.DataFrame(ctxs))
    return ctxs

# Cell
@patch
def blurr_predict(self:Learner, items, rm_type_tfms=None):
    hf_before_batch_tfm = get_blurr_tfm(self.dls.before_batch)

    is_split_str = hf_before_batch_tfm.is_split_into_words and isinstance(items[0], str)
    is_df = isinstance(items, pd.DataFrame)

    if (not is_df and (is_split_str or not is_listy(items))): items = [items]
    dl = self.dls.test_dl(items, rm_type_tfms=rm_type_tfms, num_workers=0)

    with self.no_bar():
        probs, _, decoded_preds = self.get_preds(dl=dl, with_input=False, with_decoded=True)

    trg_tfms = self.dls.tfms[self.dls.n_inp:]

    outs = []
    probs, decoded_preds = L(probs), L(decoded_preds)
    for i in range(len(items)):
        item_probs = probs.itemgot(i)
        item_dec_preds = decoded_preds.itemgot(i)
        item_dec_labels = tuplify([tfm.decode(item_dec_preds[tfm_idx]) for tfm_idx, tfm in enumerate(trg_tfms)])

        outs.append((item_dec_labels, item_dec_preds, item_probs))

    return outs

# Cell
import onnxruntime as ort
from onnxruntime.quantization import quantize_dynamic, QuantType

# Cell
@patch
def blurr_to_onnx(self:Learner, fname='export', path=None, quantize=False, excluded_input_names=[]):
    """Export model to `ONNX` format"""
    if (path == None): path = self.path

    dummy_b = self.dls.one_batch()

    # inputs
    for n in excluded_input_names:
        if (n in dummy_b[0]): del dummy_b[0][n]

    input_names = list(dummy_b[0].keys())
    dynamic_axes = { n: {0:'batch_size', 1:'sequence'} for n in input_names if n in self.model.hf_model_fwd_args}

    # outputs
    output_names = [ f'output_{i}' for i in range(len(dummy_b) - self.dls.n_inp) ]
    for n in output_names: dynamic_axes[n] = { 0:'batch_size' }

    torch.onnx.export(model=self.model,
                      args=dummy_b[:self.dls.n_inp],    # everything but the targets
                      f=self.path/f'{fname}.onnx',      # onnx filename
                      opset_version=11,                 # required for get errors
                      input_names=input_names,          # transformer dictionary keys for input
                      output_names=output_names,        # one for each target
                      dynamic_axes=dynamic_axes)        # see above

    if (quantize):
        quant_model_fpath = self.path/f'{fname}-quant.onnx'
        quant_model = quantize_dynamic(self.path/f'{fname}.onnx', quant_model_fpath, weight_type=QuantType.QUInt8)

    dls_export = self.dls.new_empty()
    dls_export.loss_func = self.loss_func
    dls_export.hf_model_fwd_args = self.model.hf_model_fwd_args # we need this to exclude non-model args in onnx

    torch.save(dls_export, self.path/f'{fname}-dls.pkl', pickle_protocol=2)

# Cell
class blurrONNX():
    def __init__(self, fname='export', path=Path('.'), use_quant_version=False):
        self.fname, self.path = fname, path

        onnx_fname = f'{fname}-quant.onnx' if (use_quant_version) else f'{fname}.onnx'
        self.ort_session = ort.InferenceSession(str(self.path/onnx_fname))

        self.dls = torch.load(f'{self.path}/{fname}-dls.pkl')
        self.trg_tfms = self.dls.tfms[self.dls.n_inp:]
        self.tok_is_split_into_words = self.dls.before_batch[0].is_split_into_words
        self.hf_model_fwd_args = self.dls.hf_model_fwd_args

    def predict(self, items, rm_type_tfms=None):
        is_split_str = self.tok_is_split_into_words and isinstance(items[0], str)
        is_df = isinstance(items, pd.DataFrame)

        if (not is_df and (is_split_str or not is_listy(items))): items = [items]
        dl = self.dls.test_dl(items, rm_type_tfms=rm_type_tfms, num_workers=0)

        outs = []
        for b in dl:
            xb = b[0]
            inp = self._to_np(xb)

            # remove any args not found in the transformers forward func
            for k in list(inp.keys()):
                if (k not in self.hf_model_fwd_args): del inp[k]

            res = self.ort_session.run(None, inp)
            tensor_res = [ tensor(r) for r in res ]
            probs = L([ self.dls.loss_func.activation(tr) for tr in tensor_res ])
            decoded_preds = L([ self.dls.loss_func.decodes(tr) for tr in tensor_res ])

            for i in range(len(xb['input_ids'])):
                item_probs = probs.itemgot(i)
                item_dec_preds = decoded_preds.itemgot(i)
                item_dec_labels = tuplify([tfm.decode(item_dec_preds[tfm_idx])
                                           for tfm_idx, tfm in enumerate(self.trg_tfms)])

                outs.append((item_dec_labels, item_dec_preds, item_probs))

        return outs

    #----- utility -----
    def _to_np(self, xb): return { k: v.cpu().numpy() for k,v in xb.items() }